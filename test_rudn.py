import unittest
from claim_calculator import calculate_insurance_payout

class TestClaimCalculator(unittest.TestCase):
    def test_calculate_insurance_payout_below_deductible(self):
        # 测试账单金额低于免赔额的情况
        result = calculate_insurance_payout(400, 500, 0.8)
        self.assertEqual(result, 0.0)

    def test_calculate_insurance_payout_above_deductible(self):
        # 测试账单金额高于免赔额的情况
        result = calculate_insurance_payout(1000, 500, 0.8)
        self.assertEqual(result, 400.0)  # (1000 - 500) * 0.8 = 400

    def test_calculate_insurance_payout_equal_deductible(self):
        # 测试账单金额等于免赔额的情况
        result = calculate_insurance_payout(500, 500, 0.8)
        self.assertEqual(result, 0.0)

    def test_calculate_insurance_payout_with_different_ratio(self):
        # 测试不同赔付比例
        result = calculate_insurance_payout(1500, 500, 0.9)
        self.assertEqual(result, 900.0)  # (1500 - 500) * 0.9 = 900

if __name__ == '__main__':
    unittest.main()