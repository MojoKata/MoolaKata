"""Maps each entity onto its table (requirements S14.1.2). Imported once, at start."""

from sqlalchemy import event
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import registry

from .entities import Record, SoftDeleted, _now
from .entities import accounts as acc
from .entities import assets as asx
from .entities import budgets as bd
from .entities import connector as cn
from .entities import education as ed
from .entities import giving as gv
from .entities import links as lk
from .entities import prices as pr
from .entities import projections as pj
from .entities import receipts as rc
from .entities import sharing as sh
from .entities import taxes as tx
from .entities.alerts import Alert, AlertState
from .entities.core import Activity, QueuedEmail, Secret, Setting, TaskRun
from .entities.users import (
    AccessToken,
    Group,
    OneTimeToken,
    RecoveryCode,
    Session,
    SignupRequest,
    User,
    UserGroup,
)
from .tables import (
    accounts,
    activity,
    alerts,
    assets,
    budgets,
    connector,
    core,
    education,
    giving,
    links,
    loans,
    options,
    people,
    prices,
    projections,
    receipts,
    sharing,
    taxes,
    users,
    wallets,
)

mapper_registry = registry()
_done = False


def _map(entity, table, **kw) -> None:
    """Map an entity. A soft-deleting table's `deleted` is generated from `deletedAt` (schema.md
    §4.1), so the ORM never writes it: the entity's property reads it, and in a query it is
    `deletedAt IS NOT NULL`."""
    if not table.info.get("softDelete"):
        mapper_registry.map_imperatively(entity, table, **kw)
        return
    mapper_registry.map_imperatively(entity, table, exclude_properties=["deleted"], **kw)
    entity.deleted = hybrid_property(
        SoftDeleted.deleted.fget, expr=lambda cls: cls.deletedAt.is_not(None)
    )


def _versioned(entity, table, **kw) -> None:
    _map(entity, table, version_id_col=table.c.version, **kw)


def map_all() -> None:
    global _done
    if _done:
        return
    _done = True
    _versioned(User, users.User)
    _versioned(Group, users.Group)
    _versioned(AccessToken, users.AccessToken)
    _map(UserGroup, users.UserGroups)
    _map(Session, users.Session)
    _map(OneTimeToken, users.OneTimeToken)
    _map(RecoveryCode, users.RecoveryCode)
    _map(SignupRequest, users.SignupRequest)
    _map(Alert, alerts.Alert)
    _map(AlertState, alerts.AlertState)
    for entity, table in (
        (acc.Category, accounts.Category),
        (acc.Account, accounts.Account),
        (acc.Instrument, accounts.Instrument),
        (acc.ImportMapping, accounts.ImportMapping),
        (acc.Rule, accounts.Rule),
        (acc.StatementLayout, accounts.StatementLayout),
        (acc.Loan, loans.Loan),
        (acc.OptionContract, options.OptionContract),
        (acc.Strategy, options.Strategy),
        (acc.WalletKey, wallets.WalletKey),
        (acc.PayoffPlan, loans.PayoffPlan),
        (tx.TaxBook, taxes.TaxBook),
        (tx.Filing, taxes.Filing),
        (tx.TaxBookDependent, taxes.TaxBookDependent),
        (tx.EstimatedPayment, taxes.EstimatedPayment),
        (tx.TaxBookChange, taxes.TaxBookChange),
        (tx.TaxDocument, taxes.TaxDocument),
        (gv.GivingPlan, giving.GivingPlan),
        (gv.Organisation, giving.Organisation),
        (gv.Donation, giving.Donation),
        (ed.Person, people.Person),
        (ed.Relationship, people.Relationship),
        (ed.GiftPlan, people.GiftPlan),
        (ed.Occasion, people.Occasion),
        (ed.Gift, people.Gift),
        (ed.EducationPlan, education.EducationPlan),
        (ed.Contribution, education.Contribution),
        (ed.QualifiedExpense, education.QualifiedExpense),
        (asx.Item, assets.Item),
        (asx.ItemValuation, assets.ItemValuation),
        (asx.Improvement, assets.Improvement),
        (acc.Import, accounts.Import),
        (acc.Transaction, accounts.Transaction),
        (acc.Split, accounts.Split),
        (acc.Reimbursement, accounts.Reimbursement),
        (acc.Lot, accounts.Lot),
        (acc.Holding, accounts.Holding),
        (acc.Anchor, accounts.Anchor),
        (acc.HoldingCheck, accounts.HoldingCheck),
        (acc.TransferMatch, accounts.TransferMatch),
        (acc.Reconciliation, accounts.Reconciliation),
    ):
        _versioned(entity, table)
    _versioned(acc.Tag, accounts.Tag)
    _map(acc.TransactionTag, accounts.TransactionTags)
    _map(acc.RuleTag, accounts.RuleTags)
    _versioned(acc.LotPick, accounts.LotPick)
    _versioned(pr.PriceSource, prices.PriceSource)
    _versioned(pr.Price, prices.Price)
    _versioned(pr.TypedPrice, prices.TypedPrice)
    _versioned(sh.Portfolio, sharing.Portfolio)
    _versioned(sh.Share, sharing.Share)
    _map(sh.PortfolioAccount, sharing.PortfolioAccounts)
    _versioned(bd.Budget, budgets.Budget)
    _versioned(bd.BudgetLine, budgets.BudgetLine)
    _versioned(bd.BudgetMove, budgets.BudgetMove)
    _versioned(bd.BudgetReview, budgets.BudgetReview)
    _versioned(bd.BudgetAccount, budgets.BudgetAccount)
    _map(bd.BudgetLeaveOut, budgets.BudgetLeaveOuts)
    _versioned(rc.Receipt, receipts.Receipt)
    _versioned(rc.ReceiptLink, receipts.ReceiptLink)
    _map(rc.ReceiptTag, receipts.ReceiptTags)
    _map(ed.GiftPerson, people.GiftPersons)
    _map(acc.WashSale, options.WashSale)
    _versioned(acc.StrategyLeg, options.StrategyLeg)
    _map(acc.WalletAddress, wallets.WalletAddress)
    _versioned(tx.TaxBookFiler, taxes.TaxBookFiler)
    _versioned(tx.TaxBookAccount, taxes.TaxBookAccount)
    _map(tx.TaxDependentAccount, taxes.TaxDependentAccounts)
    _versioned(pj.AssumptionSet, projections.AssumptionSet)
    _versioned(pj.Projection, projections.Projection)
    _versioned(pj.TaxFigure, projections.TaxFigure)
    _map(pj.ShownProjection, projections.ShownProjections)
    _versioned(sh.CountedAccount, sharing.CountedAccount)
    _versioned(Setting, core.Setting)
    _versioned(lk.Link, links.Link)
    _versioned(cn.Connector, connector.Connector)
    _versioned(cn.Connection, connector.Connection)
    _map(lk.LinkedItem, links.LinkedItem)
    _map(lk.LinkSent, links.LinkSent)
    _map(lk.LinkFile, links.LinkFile)
    _versioned(lk.LinkColour, links.LinkColour)
    _map(Secret, core.Secret)
    _map(TaskRun, core.TaskRun)
    _map(QueuedEmail, core.QueuedEmail)
    _map(Activity, activity.Activity)


@event.listens_for(Record, "before_update", propagate=True)
def _touch(mapper, connection, target) -> None:
    target.updatedAt = _now()
