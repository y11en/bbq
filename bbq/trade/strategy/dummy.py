from .strategy import Strategy
from ..account import Account
from ..trade_signal import TradeSignal
from datetime import datetime
from bbq.trade.enum import event


class Dummy(Strategy):
    def __init__(self, strategy_id, account: Account):
        super().__init__(strategy_id=strategy_id, account=account)

        self.test_codes_buy = []
        self.test_codes_sell = []

        self.trade_date_buy = {}
        self.trade_date_sell = {}

    def name(self):
        return '神算子Dummy策略'

    async def on_quot(self, evt, payload):
        self.log.info('dummy strategy on_quot: evt={}, payload={}'.format(evt, payload))
        if evt == event.evt_quotation:
            for quot in payload['list'].values():
                code, name, price = quot['code'], quot['name'], quot['close']
                if self.is_index(code):
                    continue

                day_time = quot['day_time']
                trade_date = datetime(year=day_time.year, month=day_time.month, day=day_time.day)
                is_sig, signal = False, ''

                if code not in self.test_codes_buy:
                    is_sig = True
                    signal = TradeSignal.sig_buy
                    self.test_codes_buy.append(code)
                    self.trade_date_buy[code] = trade_date
                if code not in self.test_codes_sell and code in self.test_codes_buy:
                    if self.trade_date_buy[code] != trade_date:
                        is_sig = True
                        signal = TradeSignal.sig_sell
                        self.test_codes_sell.append(code)
                        self.trade_date_sell[code] = trade_date

                if is_sig:
                    sig = TradeSignal(self.get_uuid(), self.account,
                                      source=self.get_obj_id(typ=TradeSignal.strategy), source_name=self.name(),
                                      signal=signal, code=code, name=name, price=price, time=day_time)

                    await self.emit('signal', (event.evt_sig_buy if signal == sig.sig_buy else event.evt_sig_sell), sig)
