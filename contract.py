from trytond.pool import Pool ,PoolMeta

class ContractConsumption(metaclass=PoolMeta):
    __name__ = 'contract.consumption'

    @classmethod
    def _invoice(cls, consumptions):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        invoices = super()._invoice(consumptions)
        Invoice.reset_verifactu_keys(invoices)
        return invoices
