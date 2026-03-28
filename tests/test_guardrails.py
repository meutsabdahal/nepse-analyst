import unittest

from nepse_analyst.guardrails import get_guardrail_type


class GuardrailTests(unittest.TestCase):
    def test_prediction_query_detected(self) -> None:
        self.assertEqual(
            get_guardrail_type("Will NABIL stock go up tomorrow?"), "prediction"
        )

    def test_advice_query_detected(self) -> None:
        self.assertEqual(get_guardrail_type("Should I buy HIDCL now?"), "advice")

    def test_nepali_prediction_detected(self) -> None:
        self.assertEqual(get_guardrail_type("NABIL को मूल्य बढ्छ?"), "prediction")

    def test_nepali_advice_detected(self) -> None:
        self.assertEqual(get_guardrail_type("म अहिले कुन सेयर किन्नु पर्छ?"), "advice")


if __name__ == "__main__":
    unittest.main()
