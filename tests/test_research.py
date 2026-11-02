import json
import unittest

import httpx

from wedding_assistant.research import (
    DemoResearchProvider,
    ORGANIZER_SCHEMA,
    ResearchError,
    ResearchReport,
    Source,
    TavilyResearchProvider,
)


SOURCE = {
    "title": "봄빛 스튜디오 공식 안내",
    "url": "https://vendor.example/studio",
    "content": "봄빛 스튜디오는 서울 강남에 있습니다. 봄빛 스튜디오 촬영 기본 가격은 150만원입니다. 봄빛 스튜디오는 사진 색감이 좋았지만 추가금이 있었습니다.",
    "score": 0.987654,
    "published_date": "2026-10-01",
}


class FakeOrganizer:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def complete_json(self, prompt, schema):
        self.calls.append((prompt, schema))
        if self.error is not None:
            raise self.error
        return self.result


class ResearchTests(unittest.TestCase):
    def provider(self, handler, **kwargs):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return TavilyResearchProvider("test-search-key", client=client, **kwargs)

    def test_two_bounded_queries_dedupe_and_no_search_score_as_rating(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"results": [SOURCE]})

        report = self.provider(handler).research("스튜디오", "서울", "200만원")
        self.assertEqual(2, len(requests))
        self.assertEqual(1, len(report.sources))
        self.assertNotIn("0.987654", report.text())
        self.assertIn("검증된 평점이 아닙니다", report.text())
        self.assertIn("검색 발췌", report.text())
        self.assertIn("2026-10-01", report.text())
        self.assertIn("200만원", report.summary)
        queries = []
        for request in requests:
            body = json.loads(request.content)
            self.assertEqual(5, body["max_results"])
            self.assertEqual("basic", body["search_depth"])
            self.assertFalse(body["auto_parameters"])
            self.assertEqual("Bearer test-search-key", request.headers["Authorization"])
            queries.append(body["query"])
        self.assertEqual(["서울 스튜디오 업체 가격 공식", "서울 스튜디오 후기 추가금 불만 협찬"], queries)

    def test_signature_ignores_time_order_and_wording_but_tracks_evidence(self):
        a = Source("a", "https://a.example/", "가격 100만원", checked_at="yesterday")
        b = Source("b", "https://b.example/", "후기", checked_at="yesterday")
        first = ResearchReport("촬영", "서울", "첫 번째 표현", [a, b])
        second = ResearchReport("촬영", "서울", "다른 표현", [b, Source("a", "https://a.example/", "가격 100만원", checked_at="today")])
        changed = ResearchReport("촬영", "서울", "첫 번째 표현", [Source("a", "https://a.example/", "가격 200만원")])
        self.assertEqual(first.signature, second.signature)
        self.assertNotEqual(first.signature, changed.signature)
        self.assertEqual(first.signature, first.as_dict()["signature"])

    def test_demo_is_explicitly_fictional(self):
        report = DemoResearchProvider().research("메이크업", "서울")
        self.assertIn("실제 업체 검색을 실행하지 않았습니다", report.text())
        self.assertIn("example.invalid", report.sources[0].url)

    def test_no_results(self):
        report = self.provider(lambda _: httpx.Response(200, json={"results": []})).research("촬영", "서울")
        self.assertEqual([], report.sources)
        self.assertIn("검색 결과가 없습니다", report.summary)

    def test_both_search_failures_raise_without_echoing_secrets(self):
        provider = self.provider(lambda _: httpx.Response(401, text="test-search-key is secret"))
        with self.assertRaises(ResearchError) as error:
            provider.research("촬영", "서울")
        self.assertNotIn("test-search-key", str(error.exception))

    def test_network_error_is_handled(self):
        def handler(request):
            raise httpx.ConnectError("connection failed", request=request)

        with self.assertRaises(ResearchError):
            self.provider(handler).research("촬영", "서울")

    def test_partial_search_failure_retains_result_with_warning(self):
        calls = 0

        def handler(_):
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429)
            return httpx.Response(200, json={"results": [SOURCE]})

        report = self.provider(handler).research("촬영", "서울")
        self.assertEqual(1, len(report.sources))
        self.assertIn("일부 검색 요청이 실패", report.summary)

    def test_malformed_search_json_is_handled(self):
        with self.assertRaises(ResearchError):
            self.provider(lambda _: httpx.Response(200, text="not JSON")).research("촬영", "서울")

    def test_response_bounds_and_urls(self):
        results = [
            {"title": "x" * 1000, "url": f"https://{i}.example/", "content": "x" * 8000}
            for i in range(8)
        ]
        report = self.provider(lambda _: httpx.Response(200, json={"results": results})).research("촬영", "서울")
        self.assertEqual(5, len(report.sources))
        self.assertEqual(3000, len(report.sources[0].excerpt))
        self.assertEqual(300, len(report.sources[0].title))
        bad = self.provider(lambda _: httpx.Response(200, json={"results": [{"url": "javascript:alert(1)", "content": "bad"}]})).research("촬영", "서울")
        self.assertEqual([], bad.sources)

    def test_oauth_organizer_renders_only_grounded_quotes_and_drops_fabricated_fields(self):
        vendors = [{
            "name": "봄빛 스튜디오",
            "price": "999만원",
            "rating": "4.99",
            "evidence": [
                {"kind": "region", "url": SOURCE["url"], "quote": "봄빛 스튜디오는 서울 강남에 있습니다."},
                {"kind": "price", "url": SOURCE["url"], "quote": "봄빛 스튜디오 촬영 기본 가격은 150만원입니다."},
                {"kind": "review_pro", "url": "https://fabricated.example/", "quote": "봄빛 스튜디오는 최고입니다."},
                {"kind": "review_con", "url": SOURCE["url"], "quote": "봄빛 스튜디오에 계약 취소 피해가 많습니다."},
            ],
        }]

        organizer = FakeOrganizer({"vendors": vendors})

        def handler(request):
            self.assertEqual("api.tavily.com", request.url.host)
            return httpx.Response(200, json={"results": [SOURCE]})

        report = self.provider(handler, organizer=organizer).research("촬영", "서울")
        self.assertIn("150만원", report.summary)
        self.assertNotIn("999만원", report.summary)
        self.assertNotIn("4.99", report.summary)
        self.assertNotIn("fabricated", report.summary)
        self.assertNotIn("계약 취소 피해", report.summary)
        self.assertIn("후기 장단점: 확인되지 않음", report.summary)
        self.assertEqual(1, len(organizer.calls))
        prompt, schema = organizer.calls[0]
        self.assertIn(SOURCE["content"], prompt)
        self.assertIn("untrusted reference data", prompt)
        self.assertEqual(ORGANIZER_SCHEMA, schema)
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["properties"]["vendors"]["items"]["additionalProperties"])

    def test_quote_from_other_vendor_not_attributed(self):
        organizer = FakeOrganizer({"vendors": [{
                "name": "없는 업체",
                "evidence": [{"kind": "price", "url": SOURCE["url"], "quote": "봄빛 스튜디오 촬영 기본 가격은 150만원입니다."}],
            }]})

        report = self.provider(lambda _: httpx.Response(200, json={"results": [SOURCE]}),
                               organizer=organizer).research("촬영", "서울")
        self.assertNotIn("없는 업체", report.summary)
        self.assertIn("자동 비교표를 생략", report.summary)

    def test_oauth_failure_surfaces_without_api_fallback_or_fake_success(self):
        calls = []
        organizer = FakeOrganizer(error=RuntimeError("OAuth expired; private credential detail"))

        def handler(request):
            calls.append(request)
            self.assertEqual("api.tavily.com", request.url.host)
            return httpx.Response(200, json={"results": [SOURCE]})

        with self.assertRaises(ResearchError) as error:
            self.provider(handler, organizer=organizer).research("촬영", "서울")
        self.assertEqual(2, len(calls))
        self.assertEqual(1, len(organizer.calls))
        self.assertIn("ChatGPT OAuth 요약에 실패", str(error.exception))
        self.assertIn("완료 처리하지 않았", str(error.exception))
        self.assertNotIn("private credential", str(error.exception))

    def test_config_and_input_validation(self):
        with self.assertRaises(ValueError):
            TavilyResearchProvider("")
        with self.assertRaises(ValueError):
            TavilyResearchProvider("key", organizer=object())
        with self.assertRaises(TypeError):
            TavilyResearchProvider("key", llm_api_key="no-api-key-option")
        provider = self.provider(lambda _: self.fail("must not make requests"))
        with self.assertRaises(ValueError):
            provider.research("", "서울")
        with self.assertRaises(ValueError):
            provider.research("촬영", "")

    def test_wrong_oauth_response_shapes_are_not_marked_successful(self):
        for payload in [[], {}, "not JSON", {"vendors": None}, {"vendors": "bad"}]:
            with self.subTest(payload=payload):
                with self.assertRaises(ResearchError):
                    self.provider(lambda _: httpx.Response(200, json={"results": [SOURCE]}),
                                  organizer=FakeOrganizer(payload)).research("촬영", "서울")

    def test_no_organizer_is_explicitly_a_source_digest(self):
        report = self.provider(lambda _: httpx.Response(200, json={"results": [SOURCE]})).research("촬영", "서울")
        self.assertIn("ChatGPT OAuth 요약을 사용하지 않은 검색 발췌", report.summary)

    def test_no_sources_do_not_require_ai_inference(self):
        organizer = FakeOrganizer(error=AssertionError("must not infer without sources"))
        report = self.provider(lambda _: httpx.Response(200, json={"results": []}),
                               organizer=organizer).research("촬영", "서울")
        self.assertEqual([], organizer.calls)
        self.assertIn("검색 결과가 없습니다", report.summary)


if __name__ == "__main__":
    unittest.main()
