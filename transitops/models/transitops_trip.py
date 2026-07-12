# -*- coding: utf-8 -*-
"""
transitops_trip.py
==================
Trip dispatching model — the operational hub of TransitOps.
Enforces all mandatory business rules around vehicle/driver assignment,
cargo limits, and status cascades at the ORM level (not just in UI domains).
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from datetime import date


class TransitOpsTrip(models.Model):
    """
    Represents a single freight or passenger transport trip from creation
    through completion or cancellation.
    """

    _name = 'transitops.trip'
    _description = 'TransitOps Trip'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'name'

    # ── Identity & Sequence ───────────────────────────────────────────────────
    name = fields.Char(
        string='Trip Reference',
        readonly=True,
        default=lambda self: _('New'),
        copy=False,
        help='Auto-generated trip reference (e.g., TRIP-2024-0001).',
    )

    # ── Route Fields ─────────────────────────────────────────────────────────
    source_location = fields.Char(
        string='Source Location',
        required=True,
        help='Starting point of the trip (city, address, or depot name).',
    )
    destination_location = fields.Char(
        string='Destination Location',
        required=True,
        help='End point of the trip.',
    )
    planned_distance = fields.Float(
        string='Planned Distance (km)',
        help='Estimated distance from source to destination in kilometres.',
    )

    # ── Assignment Fields ─────────────────────────────────────────────────────
    vehicle_id = fields.Many2one(
        comodel_name='transitops.vehicle',
        string='Vehicle',
        tracking=True,
        domain=[('status', '=', 'available'), ('active', '=', True)],
        help='Vehicle assigned to this trip. Only vehicles with "available" status '
             'can be selected. The domain is enforced again at dispatch.',
    )
    driver_id = fields.Many2one(
        comodel_name='transitops.driver',
        string='Driver',
        tracking=True,
        domain=[
            ('status', '=', 'available'),
            ('is_license_expired', '=', False),
        ],
        help='Driver assigned to this trip. Only available, non-suspended drivers '
             'with valid licenses can be selected.',
    )

    # ── Cargo Fields ─────────────────────────────────────────────────────────
    cargo_weight = fields.Float(
        string='Cargo Weight (kg)',
        required=True,
        help='Weight of cargo to be transported. Must not exceed the vehicle\'s '
             'max_load_capacity.',
    )
    cargo_description = fields.Text(
        string='Cargo Description',
        help='Brief description of the cargo contents.',
    )

    # ── Scheduling ───────────────────────────────────────────────────────────
    planned_departure = fields.Datetime(
        string='Planned Departure',
        help='Expected departure date and time.',
    )
    actual_departure = fields.Datetime(
        string='Actual Departure',
        help='Actual departure date and time (filled on dispatch).',
    )
    actual_arrival = fields.Datetime(
        string='Actual Arrival',
        help='Actual arrival date and time (filled on completion).',
    )

    # ── Completion Data ───────────────────────────────────────────────────────
    actual_distance = fields.Float(
        string='Actual Distance (km)',
        help='Actual kilometres driven, recorded when the trip is completed.',
    )
    final_odometer = fields.Float(
        string='Final Odometer Reading (km)',
        help='Odometer reading at trip end. Used to update the vehicle\'s odometer.',
    )
    fuel_consumed = fields.Float(
        string='Fuel Consumed (litres)',
        help='Total fuel used during this trip, in litres.',
    )
    notes = fields.Text(
        string='Trip Notes',
        help='Any remarks, incidents, or observations recorded during the trip.',
    )

    # ── State / Workflow ──────────────────────────────────────────────────────
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('dispatched', 'Dispatched'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
        help='Trip lifecycle state. Transitions are enforced by action methods.',
    )

    # ── Computed Helper Fields ────────────────────────────────────────────────
    vehicle_capacity = fields.Float(
        string='Vehicle Capacity (kg)',
        related='vehicle_id.max_load_capacity',
        readonly=True,
        help='Max load capacity of the assigned vehicle (read-only, for display).',
    )
    cargo_utilization = fields.Float(
        string='Cargo Utilization (%)',
        compute='_compute_cargo_utilization',
        help='Percentage of vehicle capacity being used by the current cargo.',
    )
    is_overloaded = fields.Boolean(
        string='Overloaded',
        compute='_compute_cargo_utilization',
        help='True if cargo_weight exceeds vehicle max_load_capacity.',
    )

    # ── Compute Methods ───────────────────────────────────────────────────────
    @api.depends('cargo_weight', 'vehicle_id.max_load_capacity')
    def _compute_cargo_utilization(self):
        """Calculate what percentage of the vehicle's capacity is being used."""
        for trip in self:
            if trip.vehicle_id and trip.vehicle_id.max_load_capacity > 0:
                utilization = (trip.cargo_weight / trip.vehicle_id.max_load_capacity) * 100
                trip.cargo_utilization = utilization
                trip.is_overloaded = utilization > 100
            else:
                trip.cargo_utilization = 0.0
                trip.is_overloaded = False

    # ── ORM Overrides ─────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        """Auto-assign trip sequence on creation."""
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('transitops.trip') or _('New')
        return super().create(vals_list)

    # ── Hard Business-Rule Constraints (ORM level) ────────────────────────────
    @api.constrains('cargo_weight', 'vehicle_id')
    def _check_cargo_weight(self):
        """
        Rule 5: cargo_weight must not exceed vehicle's max_load_capacity.
        Enforced at the ORM level so it fires even on programmatic writes,
        not just through the dispatch action.
        """
        for trip in self:
            if (
                trip.vehicle_id
                and trip.cargo_weight > 0
                and trip.vehicle_id.max_load_capacity > 0
                and trip.cargo_weight > trip.vehicle_id.max_load_capacity
            ):
                raise ValidationError(_(
                    'Cargo weight (%.2f kg) exceeds the maximum load capacity of '
                    'vehicle "%s" (%.2f kg). Please reduce cargo weight or assign '
                    'a vehicle with greater capacity.',
                    trip.cargo_weight,
                    trip.vehicle_id.name,
                    trip.vehicle_id.max_load_capacity,
                ))

    @api.constrains('vehicle_id', 'state')
    def _check_vehicle_availability_on_assign(self):
        """
        Rule 2 & 4: Vehicle must not be retired, in_shop, or on_trip
        when being assigned to a new trip.
        """
        for trip in self:
            if trip.vehicle_id and trip.state in ('draft', 'dispatched'):
                vehicle = trip.vehicle_id
                if vehicle.status == 'retired':
                    raise ValidationError(_(
                        'Vehicle "%s" is retired and cannot be assigned to trips.',
                        vehicle.name,
                    ))
                if vehicle.status == 'in_shop':
                    raise ValidationError(_(
                        'Vehicle "%s" is currently in maintenance and cannot be assigned to trips.',
                        vehicle.name,
                    ))
                # Check another active trip (excluding the current record)
                if vehicle.status == 'on_trip':
                    other_active = self.search([
                        ('vehicle_id', '=', vehicle.id),
                        ('state', '=', 'dispatched'),
                        ('id', '!=', trip.id),
                    ])
                    if other_active:
                        raise ValidationError(_(
                            'Vehicle "%s" is already on an active trip (%s) and '
                            'cannot be double-booked.',
                            vehicle.name,
                            other_active[0].name,
                        ))

    @api.constrains('driver_id', 'state')
    def _check_driver_availability_on_assign(self):
        """
        Rule 3 & 4: Driver must not be suspended, on_trip, or have expired license
        when being assigned to a trip in draft or dispatched state.
        """
        for trip in self:
            if trip.driver_id and trip.state in ('draft', 'dispatched'):
                driver = trip.driver_id
                if driver.status == 'suspended':
                    raise ValidationError(_(
                        'Driver "%s" is suspended and cannot be assigned to trips.',
                        driver.name,
                    ))
                if driver.is_license_expired:
                    raise ValidationError(_(
                        'Driver "%s" has an expired license (expired: %s). '
                        'The license must be renewed before dispatching.',
                        driver.name,
                        driver.license_expiry_date,
                    ))
                if driver.status == 'on_trip':
                    other_active = self.search([
                        ('driver_id', '=', driver.id),
                        ('state', '=', 'dispatched'),
                        ('id', '!=', trip.id),
                    ])
                    if other_active:
                        raise ValidationError(_(
                            'Driver "%s" is already on an active trip (%s) and '
                            'cannot be assigned to a second trip simultaneously.',
                            driver.name,
                            other_active[0].name,
                        ))

    # ── State Transition Action Methods ───────────────────────────────────────
    def action_dispatch(self):
        """
        Transition: draft → dispatched

        Validation sequence (all raise ValidationError on failure):
          1. Trip must be in draft state.
          2. Vehicle must be assigned, available, not retired, not in_shop.
          3. Driver must be assigned, available, not suspended, license not expired.
          4. Cargo weight must not exceed vehicle capacity.

        Side effects on success:
          - vehicle.status → 'on_trip'
          - driver.status → 'on_trip'
          - trip.state → 'dispatched'
          - trip.actual_departure → now
        """
        for trip in self:
            if trip.state != 'draft':
                raise ValidationError(_(
                    'Only trips in "Draft" state can be dispatched. '
                    'Trip "%s" is currently in "%s" state.',
                    trip.name,
                    trip.state,
                ))

            # ── Vehicle validation ──────────────────────────────────────────
            if not trip.vehicle_id:
                raise ValidationError(_(
                    'Please assign a vehicle before dispatching trip "%s".',
                    trip.name,
                ))
            vehicle = trip.vehicle_id
            if vehicle.status != 'available':
                raise ValidationError(_(
                    'Vehicle "%s" is not available (current status: %s). '
                    'Only available vehicles can be dispatched.',
                    vehicle.name,
                    dict(vehicle._fields['status'].selection).get(vehicle.status, vehicle.status),
                ))

            # ── Driver validation ───────────────────────────────────────────
            if not trip.driver_id:
                raise ValidationError(_(
                    'Please assign a driver before dispatching trip "%s".',
                    trip.name,
                ))
            driver = trip.driver_id
            if driver.status != 'available':
                raise ValidationError(_(
                    'Driver "%s" is not available (current status: %s).',
                    driver.name,
                    dict(driver._fields['status'].selection).get(driver.status, driver.status),
                ))
            if driver.is_license_expired:
                raise ValidationError(_(
                    'Driver "%s" has an expired license. '
                    'License expired on: %s. Renewal is required before dispatch.',
                    driver.name,
                    driver.license_expiry_date,
                ))
            if driver.status == 'suspended':
                raise ValidationError(_(
                    'Driver "%s" is suspended and cannot be dispatched.',
                    driver.name,
                ))

            # ── Cargo capacity validation ───────────────────────────────────
            if trip.cargo_weight > vehicle.max_load_capacity:
                raise ValidationError(_(
                    'Cargo weight (%.2f kg) exceeds vehicle "%s" maximum load capacity '
                    '(%.2f kg). Please adjust cargo or select a higher-capacity vehicle.',
                    trip.cargo_weight,
                    vehicle.name,
                    vehicle.max_load_capacity,
                ))

            # ── Apply state changes ─────────────────────────────────────────
            vehicle.with_context(bypass_trip_constraint=True).status = 'on_trip'
            driver.with_context(bypass_trip_constraint=True).status = 'on_trip'
            trip.write({
                'state': 'dispatched',
                'actual_departure': fields.Datetime.now(),
            })
            trip.message_post(
                body=_(
                    'Trip dispatched. Vehicle: <b>%s</b> | Driver: <b>%s</b>',
                    vehicle.name,
                    driver.name,
                )
            )
        return True

    def action_complete(self):
        """
        Transition: dispatched → completed

        Requires: actual_distance and fuel_consumed must be filled.

        Side effects on success:
          - vehicle.odometer updated to final_odometer (if provided)
          - vehicle.status → 'available'
          - driver.status → 'available'
          - trip.state → 'completed'
          - trip.actual_arrival → now
        """
        for trip in self:
            if trip.state != 'dispatched':
                raise ValidationError(_(
                    'Only dispatched trips can be marked as completed. '
                    'Trip "%s" is currently in "%s" state.',
                    trip.name,
                    trip.state,
                ))
            if not trip.actual_distance or trip.actual_distance <= 0:
                raise ValidationError(_(
                    'Please enter the actual distance driven before completing trip "%s".',
                    trip.name,
                ))
            if not trip.fuel_consumed or trip.fuel_consumed <= 0:
                raise ValidationError(_(
                    'Please enter the fuel consumed before completing trip "%s".',
                    trip.name,
                ))

            # Update vehicle odometer if final reading is provided
            vehicle = trip.vehicle_id
            if trip.final_odometer and trip.final_odometer > vehicle.odometer:
                vehicle.odometer = trip.final_odometer

            # Restore statuses
            vehicle.status = 'available'
            if trip.driver_id:
                trip.driver_id.status = 'available'

            trip.write({
                'state': 'completed',
                'actual_arrival': fields.Datetime.now(),
            })
            trip.message_post(
                body=_(
                    'Trip completed. Distance: <b>%.2f km</b> | Fuel used: <b>%.2f L</b>',
                    trip.actual_distance,
                    trip.fuel_consumed,
                )
            )
        return True

    def action_cancel(self):
        """
        Transition: dispatched → cancelled (also allows draft → cancelled)

        Side effects on success (if dispatched):
          - vehicle.status → 'available'
          - driver.status → 'available'
          - trip.state → 'cancelled'
        """
        for trip in self:
            if trip.state not in ('draft', 'dispatched'):
                raise ValidationError(_(
                    'Only draft or dispatched trips can be cancelled. '
                    'Trip "%s" is currently "%s".',
                    trip.name,
                    trip.state,
                ))

            # Restore statuses only if the trip was actually dispatched
            if trip.state == 'dispatched':
                if trip.vehicle_id and trip.vehicle_id.status == 'on_trip':
                    trip.vehicle_id.status = 'available'
                if trip.driver_id and trip.driver_id.status == 'on_trip':
                    trip.driver_id.status = 'available'

            trip.state = 'cancelled'
            trip.message_post(body=_('Trip cancelled.'))
        return True

    def action_reset_to_draft(self):
        """Reset a cancelled trip back to draft for rescheduling."""
        for trip in self:
            if trip.state != 'cancelled':
                raise ValidationError(_(
                    'Only cancelled trips can be reset to draft.',
                ))
            trip.state = 'draft'
        return True
