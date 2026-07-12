# -*- coding: utf-8 -*-
"""
transitops_driver.py
====================
Driver and safety profile model for the TransitOps module.
Tracks license validity, safety scores, compliance status, and operational state.
Business rules enforced here prevent expired or suspended drivers from being
assigned to trips at the ORM level.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from datetime import date


class TransitOpsDriver(models.Model):
    """Represents a driver in the TransitOps system with full compliance tracking."""

    _name = 'transitops.driver'
    _description = 'TransitOps Driver'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'
    _rec_name = 'name'

    # ── SQL-level Uniqueness ──────────────────────────────────────────────────
    _sql_constraints = [
        (
            'license_number_unique',
            'UNIQUE(license_number)',
            'A driver with this license number already exists. License numbers must be unique.',
        ),
    ]

    # ── Core Identity Fields ─────────────────────────────────────────────────
    name = fields.Char(
        string='Driver Name',
        required=True,
        tracking=True,
    )
    employee_id = fields.Char(
        string='Employee ID',
        help='Internal employee identifier, if applicable.',
    )
    contact_number = fields.Char(
        string='Contact Number',
        help='Primary phone number for reaching the driver.',
    )
    email = fields.Char(
        string='Email Address',
    )
    image = fields.Binary(
        string='Driver Photo',
        attachment=True,
    )
    image_filename = fields.Char(string='Photo Filename')

    # ── License & Compliance Fields ───────────────────────────────────────────
    license_number = fields.Char(
        string='License Number',
        required=True,
        tracking=True,
        help='Official driving license number. Must be unique across all drivers.',
    )
    license_category = fields.Selection(
        selection=[
            ('a', 'Category A — Motorcycles'),
            ('b', 'Category B — Light Vehicles'),
            ('c', 'Category C — Heavy Trucks'),
            ('d', 'Category D — Buses'),
            ('e', 'Category E — Articulated Vehicles'),
            ('ec', 'Category EC — Articulated Buses'),
        ],
        string='License Category',
        required=True,
        tracking=True,
        help='Class of vehicles the driver is legally authorised to operate.',
    )
    license_expiry_date = fields.Date(
        string='License Expiry Date',
        required=True,
        tracking=True,
        help='Date on which the driving license becomes invalid. '
             'Drivers with expired licenses cannot be dispatched.',
    )
    is_license_expired = fields.Boolean(
        string='License Expired',
        compute='_compute_is_license_expired',
        store=True,
        help='True if today\'s date is past the license expiry date.',
    )
    days_until_expiry = fields.Integer(
        string='Days Until Expiry',
        compute='_compute_is_license_expired',
        store=True,
        help='Number of days remaining before the license expires. Negative means already expired.',
    )

    # ── Safety & Operational Fields ───────────────────────────────────────────
    safety_score = fields.Float(
        string='Safety Score',
        default=100.0,
        digits=(5, 1),
        tracking=True,
        help='Driver safety score from 0 (worst) to 100 (best). '
             'Influenced by incident history, violations, and compliance records.',
    )
    status = fields.Selection(
        selection=[
            ('available', 'Available'),
            ('on_trip', 'On Trip'),
            ('off_duty', 'Off Duty'),
            ('suspended', 'Suspended'),
        ],
        string='Status',
        default='available',
        required=True,
        tracking=True,
        help='Current operational status. Automatically managed by trip dispatch workflow.',
    )
    compliance_status = fields.Selection(
        selection=[
            ('compliant', 'Compliant'),
            ('warning', 'Warning'),
            ('non_compliant', 'Non-Compliant'),
        ],
        string='Compliance Status',
        compute='_compute_compliance_status',
        store=True,
        help='Overall compliance: Compliant (valid license, score ≥ 70), '
             'Warning (license expires within 30 days or score 40–69), '
             'Non-Compliant (expired license, score < 40, or suspended).',
    )

    # ── Trip Back-Reference ───────────────────────────────────────────────────
    trip_ids = fields.One2many(
        comodel_name='transitops.trip',
        inverse_name='driver_id',
        string='Trip History',
    )
    total_trips_completed = fields.Integer(
        string='Trips Completed',
        compute='_compute_trip_stats',
        store=True,
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = fields.Text(
        string='Internal Notes',
        help='Additional notes about the driver — incidents, comments, etc.',
    )

    # ── Compute Methods ───────────────────────────────────────────────────────
    @api.depends('license_expiry_date')
    def _compute_is_license_expired(self):
        """Determine if license is expired and how many days remain."""
        today = date.today()
        for driver in self:
            if driver.license_expiry_date:
                delta = (driver.license_expiry_date - today).days
                driver.days_until_expiry = delta
                driver.is_license_expired = delta < 0
            else:
                driver.days_until_expiry = 0
                driver.is_license_expired = True  # No expiry date = treat as expired

    @api.depends('is_license_expired', 'days_until_expiry', 'safety_score', 'status')
    def _compute_compliance_status(self):
        """
        Derive overall compliance status from license validity, expiry proximity,
        safety score, and operational status.
        """
        for driver in self:
            if driver.status == 'suspended' or driver.is_license_expired or driver.safety_score < 40:
                driver.compliance_status = 'non_compliant'
            elif driver.days_until_expiry <= 30 or driver.safety_score < 70:
                driver.compliance_status = 'warning'
            else:
                driver.compliance_status = 'compliant'

    @api.depends('trip_ids.state')
    def _compute_trip_stats(self):
        """Count completed trips for this driver."""
        for driver in self:
            driver.total_trips_completed = len(
                driver.trip_ids.filtered(lambda t: t.state == 'completed')
            )

    # ── ORM-Level Constraints ─────────────────────────────────────────────────
    @api.constrains('license_number')
    def _check_license_number_unique(self):
        """Belt-and-suspenders uniqueness check at the Python level."""
        for driver in self:
            if driver.license_number:
                duplicate = self.search([
                    ('license_number', '=', driver.license_number),
                    ('id', '!=', driver.id),
                ])
                if duplicate:
                    raise ValidationError(_(
                        'License number "%s" is already assigned to driver "%s". '
                        'Each driver must have a unique license number.',
                        driver.license_number,
                        duplicate[0].name,
                    ))

    @api.constrains('safety_score')
    def _check_safety_score_range(self):
        """Ensure safety score stays within the valid 0–100 range."""
        for driver in self:
            if not (0.0 <= driver.safety_score <= 100.0):
                raise ValidationError(_(
                    'Safety score must be between 0 and 100. '
                    'Received: %.1f for driver "%s".',
                    driver.safety_score,
                    driver.name,
                ))

    # ── Status Transition Helpers ─────────────────────────────────────────────
    def action_suspend_driver(self):
        """Suspend a driver. Suspended drivers cannot be dispatched on trips."""
        for driver in self:
            if driver.status == 'on_trip':
                raise ValidationError(_(
                    'Cannot suspend driver "%s" while they are currently on an active trip. '
                    'Complete or cancel the trip first.',
                    driver.name,
                ))
            driver.status = 'suspended'
        return True

    def action_reinstate_driver(self):
        """Reinstate a suspended driver back to available status."""
        for driver in self:
            if driver.status != 'suspended':
                raise ValidationError(_(
                    'Only suspended drivers can be reinstated. '
                    'Driver "%s" currently has status: %s.',
                    driver.name,
                    driver.status,
                ))
            driver.status = 'available'
        return True

    def action_set_off_duty(self):
        """Mark a driver as off duty."""
        for driver in self:
            if driver.status == 'on_trip':
                raise ValidationError(_(
                    'Cannot mark driver "%s" as off duty while on an active trip.',
                    driver.name,
                ))
            driver.status = 'off_duty'
        return True

    def action_set_available(self):
        """Return a driver to available status from off_duty."""
        for driver in self:
            driver.status = 'available'
        return True
