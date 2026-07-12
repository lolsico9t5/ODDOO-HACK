# -*- coding: utf-8 -*-
"""
transitops_maintenance.py
==========================
Maintenance workflow model for TransitOps.
When a maintenance record is created (or opened), the linked vehicle's status
is automatically set to 'in_shop'. Closing the record reverts it to 'available'
unless the vehicle is retired.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class TransitOpsMaintenance(models.Model):
    """Tracks vehicle service and repair work orders."""

    _name = 'transitops.maintenance'
    _description = 'TransitOps Maintenance Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc'
    _rec_name = 'name'

    # ── Identity Fields ───────────────────────────────────────────────────────
    name = fields.Char(
        string='Work Order Reference',
        readonly=True,
        default=lambda self: _('New'),
        copy=False,
        help='Auto-generated maintenance work order reference (e.g., MNT-2024-0001).',
    )
    service_type = fields.Selection(
        selection=[
            ('oil_change', 'Oil Change'),
            ('engine_repair', 'Engine Repair'),
            ('tyre_replace', 'Tyre Replacement'),
            ('brake_service', 'Brake Service'),
            ('body_work', 'Body Work'),
            ('electrical', 'Electrical Repair'),
            ('transmission', 'Transmission Service'),
            ('ac_service', 'A/C Service'),
            ('general_inspection', 'General Inspection'),
            ('other', 'Other'),
        ],
        string='Service Type',
        required=True,
        tracking=True,
    )

    # ── Vehicle Link ──────────────────────────────────────────────────────────
    vehicle_id = fields.Many2one(
        comodel_name='transitops.vehicle',
        string='Vehicle',
        required=True,
        tracking=True,
        ondelete='restrict',
        help='Vehicle undergoing maintenance.',
    )

    # ── Financial & Schedule Fields ───────────────────────────────────────────
    cost = fields.Float(
        string='Service Cost',
        tracking=True,
        help='Total cost of this maintenance work order.',
    )
    date = fields.Date(
        string='Service Date',
        default=fields.Date.today,
        required=True,
        tracking=True,
        help='Date the maintenance work was performed or commenced.',
    )
    estimated_completion = fields.Date(
        string='Estimated Completion',
        help='Expected date for work completion.',
    )
    service_provider = fields.Char(
        string='Service Provider / Garage',
        help='Name of the garage, workshop, or technician performing the work.',
    )

    # ── Status ────────────────────────────────────────────────────────────────
    status = fields.Selection(
        selection=[
            ('in_shop', 'In Shop'),
            ('completed', 'Completed'),
        ],
        string='Status',
        default='in_shop',
        required=True,
        tracking=True,
        help='in_shop: vehicle is currently being serviced. '
             'completed: work is done and vehicle can be released.',
    )

    # ── Description ───────────────────────────────────────────────────────────
    description = fields.Text(
        string='Work Description',
        help='Detailed description of the maintenance work performed.',
    )

    # ── ORM Overrides ─────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        """
        Rule 9: Creating a maintenance record → vehicle status becomes 'in_shop'.
        Also auto-assign sequence reference.
        """
        records = super().create(vals_list)
        for record in records:
            # Auto-assign sequence
            if record.name == _('New'):
                record.name = (
                    self.env['ir.sequence'].next_by_code('transitops.maintenance')
                    or _('New')
                )
            # Set vehicle to in_shop
            if record.vehicle_id and record.status == 'in_shop':
                if record.vehicle_id.status == 'on_trip':
                    raise ValidationError(_(
                        'Cannot log maintenance for vehicle "%s" while it is on an active trip. '
                        'Complete or cancel the trip first.',
                        record.vehicle_id.name,
                    ))
                if record.vehicle_id.status != 'retired':
                    record.vehicle_id.status = 'in_shop'
        return records

    # ── Constraint ────────────────────────────────────────────────────────────
    @api.constrains('vehicle_id', 'status')
    def _check_vehicle_not_on_trip(self):
        """Prevent adding maintenance for a vehicle currently on a trip."""
        for record in self:
            if record.status == 'in_shop' and record.vehicle_id:
                active_trip = self.env['transitops.trip'].search([
                    ('vehicle_id', '=', record.vehicle_id.id),
                    ('state', '=', 'dispatched'),
                ], limit=1)
                if active_trip:
                    raise ValidationError(_(
                        'Vehicle "%s" is currently on an active trip (%s). '
                        'Maintenance cannot be logged until the trip is completed or cancelled.',
                        record.vehicle_id.name,
                        active_trip.name,
                    ))

    # ── Action Method ─────────────────────────────────────────────────────────
    def action_close(self):
        """
        Rule 10: Close the maintenance record and restore vehicle to 'available'
        unless the vehicle is 'retired'.

        Transition: in_shop → completed
        """
        for record in self:
            if record.status != 'in_shop':
                raise ValidationError(_(
                    'Only maintenance records with status "In Shop" can be closed. '
                    'Work order "%s" has status: %s.',
                    record.name,
                    record.status,
                ))
            record.status = 'completed'

            # Restore vehicle only if not retired
            if record.vehicle_id and record.vehicle_id.status != 'retired':
                # Check if another maintenance record is still in_shop for this vehicle
                other_open = self.search([
                    ('vehicle_id', '=', record.vehicle_id.id),
                    ('status', '=', 'in_shop'),
                    ('id', '!=', record.id),
                ])
                if not other_open:
                    record.vehicle_id.status = 'available'

            record.message_post(
                body=_(
                    'Maintenance completed. Service: <b>%s</b> | Cost: <b>%.2f</b>',
                    dict(self._fields['service_type'].selection).get(
                        record.service_type, record.service_type
                    ),
                    record.cost,
                )
            )
        return True
