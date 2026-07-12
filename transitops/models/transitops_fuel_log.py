# -*- coding: utf-8 -*-
"""
transitops_fuel_log.py
======================
Fuel consumption log model for TransitOps.
Each record tracks a single refuelling event for a vehicle,
including liters added, cost, and odometer at time of fuelling.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class TransitOpsFuelLog(models.Model):
    """Records individual fuel fill-up events per vehicle."""

    _name = 'transitops.fuel.log'
    _description = 'TransitOps Fuel Log'
    _order = 'date desc'
    _rec_name = 'name'

    # ── Identity ───────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Fuel Log Reference',
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
        help='Vehicle that was refuelled.',
    )
    date = fields.Date(
        string='Fuel Date',
        default=fields.Date.today,
        required=True,
        help='Date of the refuelling event.',
    )
    liters = fields.Float(
        string='Litres Added',
        required=True,
        digits=(10, 3),
        help='Number of litres of fuel added in this fill-up.',
    )
    cost_per_liter = fields.Float(
        string='Cost per Litre',
        digits=(10, 3),
        help='Fuel price per litre at the time of fuelling.',
    )
    total_cost = fields.Float(
        string='Total Fuel Cost',
        compute='_compute_total_cost',
        store=True,
        help='Total cost = litres × cost per litre.',
    )
    odometer_reading = fields.Float(
        string='Odometer at Fill-Up (km)',
        help='Odometer reading at the time of fuelling, used to track fuel efficiency.',
    )
    fuel_station = fields.Char(
        string='Fuel Station',
        help='Name or location of the fuel station where the fill-up occurred.',
    )
    notes = fields.Text(
        string='Notes',
    )

    # ── Compute Methods ───────────────────────────────────────────────────────
    @api.depends('liters', 'cost_per_liter')
    def _compute_total_cost(self):
        """Calculate total cost from volume × price."""
        for log in self:
            log.total_cost = log.liters * log.cost_per_liter

    # ── ORM Overrides ─────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        """Auto-assign sequence reference on creation."""
        records = super().create(vals_list)
        for record in records:
            if record.name == _('New'):
                record.name = (
                    self.env['ir.sequence'].next_by_code('transitops.fuel.log')
                    or _('New')
                )
        return records

    # ── Constraints ───────────────────────────────────────────────────────────
    @api.constrains('liters')
    def _check_liters_positive(self):
        """Fuel volume must be a positive number."""
        for log in self:
            if log.liters <= 0:
                raise ValidationError(_(
                    'Litres added must be a positive value. Received: %.3f.',
                    log.liters,
                ))

    @api.constrains('cost_per_liter')
    def _check_cost_non_negative(self):
        """Cost per litre must be zero or positive."""
        for log in self:
            if log.cost_per_liter < 0:
                raise ValidationError(_(
                    'Cost per litre cannot be negative. Received: %.3f.',
                    log.cost_per_liter,
                ))
