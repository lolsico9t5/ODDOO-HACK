# -*- coding: utf-8 -*-
"""
transitops_vehicle.py
=====================
Core vehicle registry model for the TransitOps module.
Tracks the full lifecycle of each transport asset, including computed
cost aggregations, fuel efficiency, and ROI derived from linked records.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class TransitOpsVehicle(models.Model):
    """Represents a single transport vehicle asset in the TransitOps fleet."""

    _name = 'transitops.vehicle'
    _description = 'TransitOps Vehicle'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'
    _rec_name = 'name'

    # ── SQL-level uniqueness (DB constraint, faster than Python check) ──────
    _sql_constraints = [
        (
            'registration_number_unique',
            'UNIQUE(registration_number)',
            'A vehicle with this registration number already exists. '
            'Registration numbers must be unique across the fleet.',
        ),
    ]

    # ── Core Identity Fields ─────────────────────────────────────────────────
    name = fields.Char(
        string='Vehicle Name / Model',
        required=True,
        tracking=True,
        help='Commercial name or model designation of the vehicle (e.g., "Toyota Hilux 2022").',
    )
    registration_number = fields.Char(
        string='Registration Number',
        required=True,
        index=True,
        tracking=True,
        help='Official government-issued registration plate number. Must be unique.',
    )
    vehicle_type = fields.Selection(
        selection=[
            ('van', 'Van'),
            ('truck', 'Truck'),
            ('bus', 'Bus'),
            ('mini_truck', 'Mini Truck'),
            ('pickup', 'Pickup'),
            ('motorcycle', 'Motorcycle'),
            ('trailer', 'Trailer'),
        ],
        string='Vehicle Type',
        required=True,
        tracking=True,
        default='van',
    )
    max_load_capacity = fields.Float(
        string='Max Load Capacity (kg)',
        required=True,
        help='Maximum cargo weight this vehicle can legally carry, in kilograms.',
    )
    odometer = fields.Float(
        string='Current Odometer (km)',
        tracking=True,
        help='Current odometer reading in kilometres. Updated automatically when trips complete.',
    )
    acquisition_cost = fields.Float(
        string='Acquisition Cost',
        help='Total cost to acquire this vehicle (purchase price + registration fees).',
    )
    status = fields.Selection(
        selection=[
            ('available', 'Available'),
            ('on_trip', 'On Trip'),
            ('in_shop', 'In Maintenance'),
            ('retired', 'Retired'),
        ],
        string='Status',
        default='available',
        required=True,
        tracking=True,
        help='Current operational status. Automatically managed by trip and maintenance workflows.',
    )
    region = fields.Char(
        string='Region / Zone',
        tracking=True,
        help='Geographic region or operational zone this vehicle is assigned to.',
    )
    image = fields.Binary(
        string='Vehicle Photo',
        attachment=True,
        help='Optional photo of the vehicle.',
    )
    image_filename = fields.Char(string='Image Filename')
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Uncheck to archive a vehicle without deleting it.',
    )

    # ── Relational Back-References (used by computed fields) ─────────────────
    fuel_log_ids = fields.One2many(
        comodel_name='transitops.fuel.log',
        inverse_name='vehicle_id',
        string='Fuel Logs',
    )
    maintenance_ids = fields.One2many(
        comodel_name='transitops.maintenance',
        inverse_name='vehicle_id',
        string='Maintenance Records',
    )
    trip_ids = fields.One2many(
        comodel_name='transitops.trip',
        inverse_name='vehicle_id',
        string='Trip History',
    )
    expense_ids = fields.One2many(
        comodel_name='transitops.expense',
        inverse_name='vehicle_id',
        string='Expenses',
    )

    # ── Computed Cost & Analytics Fields ─────────────────────────────────────
    total_fuel_cost = fields.Float(
        string='Total Fuel Cost',
        compute='_compute_total_fuel_cost',
        store=True,
        help='Sum of all fuel expenditures logged against this vehicle.',
    )
    total_maintenance_cost = fields.Float(
        string='Total Maintenance Cost',
        compute='_compute_total_maintenance_cost',
        store=True,
        help='Sum of all maintenance work orders closed against this vehicle.',
    )
    total_operational_cost = fields.Float(
        string='Total Operational Cost',
        compute='_compute_total_operational_cost',
        store=True,
        help='Total Fuel Cost + Total Maintenance Cost.',
    )
    total_trip_revenue = fields.Float(
        string='Total Trip Revenue',
        compute='_compute_total_trip_revenue',
        store=True,
        help='Aggregate revenue from all completed trips assigned to this vehicle.',
    )
    fuel_efficiency = fields.Float(
        string='Fuel Efficiency (km/L)',
        compute='_compute_fuel_efficiency',
        store=True,
        digits=(16, 2),
        help='Average kilometres driven per litre of fuel consumed, across all completed trips.',
    )
    roi = fields.Float(
        string='ROI (%)',
        compute='_compute_roi',
        store=True,
        digits=(16, 2),
        help='Return on investment = (Revenue - Operational Costs) / Acquisition Cost × 100.',
    )
    completed_trip_count = fields.Integer(
        string='Completed Trips',
        compute='_compute_trip_counts',
        store=True,
    )
    active_trip_count = fields.Integer(
        string='Active Trips',
        compute='_compute_trip_counts',
        store=True,
    )

    # ── Compute Methods ───────────────────────────────────────────────────────
    @api.depends('fuel_log_ids.total_cost')
    def _compute_total_fuel_cost(self):
        """Sum all fuel log costs for each vehicle."""
        for vehicle in self:
            vehicle.total_fuel_cost = sum(vehicle.fuel_log_ids.mapped('total_cost'))

    @api.depends('maintenance_ids.cost', 'maintenance_ids.status')
    def _compute_total_maintenance_cost(self):
        """Sum costs from completed maintenance records only."""
        for vehicle in self:
            completed = vehicle.maintenance_ids.filtered(
                lambda m: m.status == 'completed'
            )
            vehicle.total_maintenance_cost = sum(completed.mapped('cost'))

    @api.depends('total_fuel_cost', 'total_maintenance_cost')
    def _compute_total_operational_cost(self):
        """Total operational cost = fuel + maintenance."""
        for vehicle in self:
            vehicle.total_operational_cost = (
                vehicle.total_fuel_cost + vehicle.total_maintenance_cost
            )

    @api.depends('trip_ids.state')
    def _compute_total_trip_revenue(self):
        """Aggregate revenue from completed trips.
        Assumption: trip revenue is not yet a field in the spec; defaulting to 0.
        This placeholder compute exists so ROI can be calculated once revenue
        is added to the trip model in a future iteration.
        """
        for vehicle in self:
            completed = vehicle.trip_ids.filtered(lambda t: t.state == 'completed')
            vehicle.total_trip_revenue = sum(completed.mapped('revenue') if hasattr(completed, 'revenue') else [0])

    @api.depends('trip_ids.state', 'trip_ids.actual_distance', 'trip_ids.fuel_consumed')
    def _compute_fuel_efficiency(self):
        """Calculate average km/L across all completed trips."""
        for vehicle in self:
            completed = vehicle.trip_ids.filtered(
                lambda t: t.state == 'completed' and t.fuel_consumed > 0
            )
            total_distance = sum(completed.mapped('actual_distance'))
            total_fuel = sum(completed.mapped('fuel_consumed'))
            vehicle.fuel_efficiency = (
                total_distance / total_fuel if total_fuel > 0 else 0.0
            )

    @api.depends('total_trip_revenue', 'total_operational_cost', 'acquisition_cost')
    def _compute_roi(self):
        """ROI = (Revenue - Operational Costs) / Acquisition Cost × 100."""
        for vehicle in self:
            if vehicle.acquisition_cost > 0:
                vehicle.roi = (
                    (vehicle.total_trip_revenue - vehicle.total_operational_cost)
                    / vehicle.acquisition_cost
                    * 100
                )
            else:
                vehicle.roi = 0.0

    @api.depends('trip_ids.state')
    def _compute_trip_counts(self):
        """Count completed and active trips per vehicle."""
        for vehicle in self:
            vehicle.completed_trip_count = len(
                vehicle.trip_ids.filtered(lambda t: t.state == 'completed')
            )
            vehicle.active_trip_count = len(
                vehicle.trip_ids.filtered(lambda t: t.state == 'dispatched')
            )

    # ── Python-level Constraint (belt-and-suspenders over SQL constraint) ────
    @api.constrains('registration_number')
    def _check_registration_number_unique(self):
        """Enforce registration number uniqueness at the ORM level."""
        for vehicle in self:
            if vehicle.registration_number:
                duplicate = self.search([
                    ('registration_number', '=', vehicle.registration_number),
                    ('id', '!=', vehicle.id),
                ])
                if duplicate:
                    raise ValidationError(_(
                        'Registration number "%s" is already assigned to vehicle "%s". '
                        'Each vehicle must have a unique registration number.',
                        vehicle.registration_number,
                        duplicate[0].name,
                    ))

    # ── Status Transition Helper ──────────────────────────────────────────────
    def action_retire_vehicle(self):
        """Mark a vehicle as retired. Retired vehicles cannot be assigned to trips."""
        for vehicle in self:
            if vehicle.status == 'on_trip':
                raise ValidationError(_(
                    'Cannot retire vehicle "%s" while it is currently on a trip. '
                    'Complete or cancel the active trip first.',
                    vehicle.name,
                ))
            vehicle.status = 'retired'
        return True

    def action_reactivate_vehicle(self):
        """Reactivate a retired vehicle back to available status."""
        for vehicle in self:
            if vehicle.status != 'retired':
                raise ValidationError(_(
                    'Only retired vehicles can be reactivated. '
                    'Vehicle "%s" currently has status: %s.',
                    vehicle.name,
                    vehicle.status,
                ))
            vehicle.status = 'available'
        return True
