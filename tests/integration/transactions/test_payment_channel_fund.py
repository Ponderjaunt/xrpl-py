from unittest import TestCase

from tests.integration.it_utils import submit_transaction
from tests.integration.reusable_values import PAYMENT_CHANNEL, WALLET
from xrpl.models.transactions import PaymentChannelFund


class TestPaymentChannelFund(TestCase):
    def test_basic_functionality(self):
        response = submit_transaction(
            PaymentChannelFund(
                account=WALLET.classic_address,
                sequence=WALLET.sequence,
                channel=PAYMENT_CHANNEL.result["hash"],
                amount="1",
            ),
            WALLET,
        )
        self.assertTrue(response.is_successful())
