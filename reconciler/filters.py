import django_filters

from reconciler.models import AccountEntry, Counterparty, Invoice, Match, Transaction


class InvoiceFilter(django_filters.FilterSet):
    customer_id = django_filters.CharFilter(field_name="customer__customer_id")

    class Meta:
        model = Invoice
        fields = ["type", "status", "customer_id"]


class TransactionFilter(django_filters.FilterSet):
    class Meta:
        model = Transaction
        fields = ["reconciliation_status", "is_duplicate", "locked_by_user"]


class MatchFilter(django_filters.FilterSet):
    transaction_id = django_filters.CharFilter(field_name="transaction__transaction_id")
    status = django_filters.MultipleChoiceFilter(choices=Match.STATUS_CHOICES)

    class Meta:
        model = Match
        fields = ["status", "match_type", "locked_by_user", "transaction_id"]


class CounterpartyFilter(django_filters.FilterSet):
    linked = django_filters.BooleanFilter(field_name="customer", lookup_expr="isnull", exclude=True)

    class Meta:
        model = Counterparty
        fields = ["linked"]


class AccountEntryFilter(django_filters.FilterSet):
    account_type = django_filters.CharFilter(field_name="account__account_type")
    customer_id = django_filters.NumberFilter(field_name="account__customer_id")

    class Meta:
        model = AccountEntry
        fields = ["account_type", "customer_id"]
