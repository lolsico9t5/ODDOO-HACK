# -*- coding: utf-8 -*-
"""
transitops_expense.py
=====================
Miscellaneous operational expense tracking for TransitOps.
Covers tolls, miscellaneous charges, and other costs not captured
in the fuel log or maintenance records.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class TransitOpsExpense(models.Model):
    """Records individual operational expenses per vehicle or trip."""

    _name = 'transitops.expense'
    _description = 'TransitOps Operational Expense'
    _order = 'date desc'
    _rec_name = 'name'

    # ── Identity ───────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Expense Reference',
        readonly=True,
        default=lambda self: _('New'),
        copy=False,
    )

    # ── Core Fields ───────────────────────────────────────────────────────────
    vehicle_id = fields.Many2one(
        comodel_name='transitops.vehicle',
        string='Vehicle',
        required=True,
        ondelete='restrict',
        index=True,
        help='Vehicle against which this expense is recorded.',
    )
    related_trip_id = fields.Many2one(
        comodel_name='transitops.trip',
        string='Related Trip',
        ondelete='set null',
        domain="[('vehicle_id', '=', vehicle_id)]",
        help='Optional: link this expense to a specific trip for cost attribution.',
    )
    expense_type = fields.Selection(
        selection=[
            ('toll', 'Toll'),
            ('parking', 'Parking'),
            ('ferry', 'Ferry'),
            ('driver_allowance', 'Driver Allowance'),
            ('repair_minor', 'Minor Repair'),
            ('cleaning', 'Cleaning'),
            ('miscellaneous', 'Miscellaneous'),
            ('other', 'Other'),
        ],
        string='Expense Type',
        required=True,
        help='Category of the operational expense.',
    )
    date = fields.Date(
        string='Expense Date',
        default=fields.Date.today,
        required=True,
    )
    amount = fields.Float(
        string='Amount',
        required=True,
        digits=(10, 2),
        help='Expense amount in the company\'s default currency.',
    )
    receipt_number = fields.Char(
        string='Receipt / Invoice Number',
        help='Official receipt or invoice reference number for this expense.',
    )
    description = fields.Text(
        string='Description',
        help='Additional details about this expense.',
    )
    submitted_by = fields.Many2one(
        comodel_name='res.users',
        string='Submitted By',
        default=lambda self: self.env.user,
        readonly=True,
    )

    # ── ORM Overrides ─────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        """Auto-assign sequence reference on creation."""
        records = super().create(vals_list)
        for record in records:
            if record.name == _('New'):
                record.name = (
                    self.env['ir.sequence'].next_by_code('transitops.expense')
                    or _('New')
                )
        return records

    # ── Constraints ───────────────────────────────────────────────────────────
    @api.constrains('amount')
    def _check_amount_positive(self):
        """Expense amount must be positive."""
        for expense in self:
            if expense.amount <= 0:
                raise ValidationError(_(
                    'Expense amount must be greater than zero. '
                    'Received: %.2f for expense "%s".',
                    expense.amount,
                    expense.name,
                ))
