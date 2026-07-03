import tempfile
import unittest
from pathlib import Path
import json
from unittest.mock import patch

from campus_alerts.config import AppConfig
from campus_alerts.database import confirm_event, create_event, initialize_database, list_events
from campus_alerts.deepseek import assess_event, heuristic_assessment
from campus_alerts.http_server import validate_event_payload


class AssessmentTests(unittest.TestCase):
    def test_heuristic_marks_fire_as_critical(self):
        assessment = heuristic_assessment(
            {
                "type": "其他",
                "description": "宿舍楼出现火灾和浓烟",
                "location": "三号宿舍楼",
            }
        )

        self.assertEqual(assessment["type"], "消防火情")
        self.assertEqual(assessment["urgency"], "critical")
        self.assertEqual(assessment["urgency_score"], 4)

    def test_assessment_falls_back_without_key(self):
        config = AppConfig(
            host="127.0.0.1",
            port=8000,
            database_path=Path("unused.sqlite3"),
            static_dir=Path("static"),
            deepseek_api_key="",
            deepseek_api_url="https://example.invalid",
            deepseek_model="deepseek-v4-flash",
            deepseek_thinking_type="enabled",
            deepseek_reasoning_effort="high",
            deepseek_timeout_seconds=1,
        )
        assessment = assess_event(
            {
                "type": "设施故障",
                "description": "图书馆一楼电梯故障",
                "occurred_at": "2026-07-03T15:00",
                "location": "图书馆",
            },
            config,
        )

        self.assertEqual(assessment["source"], "heuristic")
        self.assertEqual(assessment["type"], "设施故障")

    def test_deepseek_request_uses_v4_flash_template(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                response_payload = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "type": "消防火情",
                                        "urgency": "critical",
                                        "urgency_score": 4,
                                        "reason": "存在火灾风险。",
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }
                return json.dumps(response_payload, ensure_ascii=False).encode("utf-8")

        def fake_urlopen(http_request, timeout):
            captured["timeout"] = timeout
            captured["headers"] = dict(http_request.header_items())
            captured["body"] = http_request.data.decode("utf-8")
            return FakeResponse()

        config = AppConfig(
            host="127.0.0.1",
            port=8000,
            database_path=Path("unused.sqlite3"),
            static_dir=Path("static"),
            deepseek_api_key="test-key",
            deepseek_api_url="https://api.deepseek.com/chat/completions",
            deepseek_model="deepseek-v4-flash",
            deepseek_thinking_type="enabled",
            deepseek_reasoning_effort="high",
            deepseek_timeout_seconds=7,
        )

        with patch("campus_alerts.deepseek.request.urlopen", fake_urlopen):
            assessment = assess_event(
                {
                    "type": "消防火情",
                    "description": "宿舍楼出现火灾和浓烟",
                    "occurred_at": "2026-07-03T15:00",
                    "location": "三号宿舍楼",
                },
                config,
            )

        request_body = json.loads(captured["body"])
        self.assertEqual(request_body["model"], "deepseek-v4-flash")
        self.assertEqual(request_body["thinking"], {"type": "enabled"})
        self.assertEqual(request_body["reasoning_effort"], "high")
        self.assertIs(request_body["stream"], False)
        self.assertEqual(captured["timeout"], 7)
        self.assertEqual(assessment["source"], "deepseek")
        self.assertEqual(assessment["urgency"], "critical")

    def test_deepseek_result_gets_local_safety_floor(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                response_payload = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "type": "其他",
                                        "urgency": "low",
                                        "urgency_score": 1,
                                        "reason": "模型认为风险较低。",
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }
                return json.dumps(response_payload, ensure_ascii=False).encode("utf-8")

        config = AppConfig(
            host="127.0.0.1",
            port=8000,
            database_path=Path("unused.sqlite3"),
            static_dir=Path("static"),
            deepseek_api_key="test-key",
            deepseek_api_url="https://api.deepseek.com/chat/completions",
            deepseek_model="deepseek-v4-flash",
            deepseek_thinking_type="enabled",
            deepseek_reasoning_effort="high",
            deepseek_timeout_seconds=7,
        )

        with patch("campus_alerts.deepseek.request.urlopen", return_value=FakeResponse()):
            assessment = assess_event(
                {
                    "type": "其他",
                    "description": "宿舍楼出现火灾和浓烟",
                    "occurred_at": "2026-07-03T15:00",
                    "location": "三号宿舍楼",
                },
                config,
            )

        self.assertEqual(assessment["type"], "消防火情")
        self.assertEqual(assessment["urgency"], "critical")
        self.assertIn("上调紧急度", assessment["reason"])


class DatabaseTests(unittest.TestCase):
    def test_create_list_and_confirm_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "events.sqlite3"
            initialize_database(database_path)
            event = create_event(
                database_path,
                {
                    "type": "安全治安",
                    "description": "校门口有人打架受伤",
                    "occurred_at": "2026-07-03T15:10",
                    "location": "东门",
                },
                {
                    "type": "安全治安",
                    "urgency": "high",
                    "urgency_score": 3,
                    "reason": "涉及人身安全。",
                    "source": "heuristic",
                },
            )

            self.assertEqual(event["status"], "pending")
            self.assertEqual(len(list_events(database_path)), 1)

            confirmed = confirm_event(database_path, event["id"])
            self.assertIsNotNone(confirmed)
            self.assertEqual(confirmed["status"], "confirmed")
            self.assertTrue(confirmed["confirmed"])


class ValidationTests(unittest.TestCase):
    def test_requires_core_fields(self):
        errors = validate_event_payload({})
        self.assertGreaterEqual(len(errors), 4)

    def test_accepts_valid_payload(self):
        errors = validate_event_payload(
            {
                "type": "医疗急救",
                "description": "操场有人晕倒需要帮助",
                "occurred_at": "2026-07-03T15:20",
                "location": "操场",
            }
        )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
