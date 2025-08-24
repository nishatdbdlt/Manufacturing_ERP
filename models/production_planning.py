from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)


class ProductionPlan(models.Model):
    _name = 'manufacturing.production.plan'
    _description = 'Production Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, date_planned asc'

    name = fields.Char('Plan Name', required=True, tracking=True)
    sequence = fields.Char('Sequence', default='New')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled')
    ], default='draft', tracking=True)

    # Planning Details
    date_planned = fields.Datetime('Planned Date', required=True, tracking=True)
    date_start = fields.Datetime('Start Date', tracking=True)
    date_end = fields.Datetime('End Date', tracking=True)
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Critical')
    ], default='1', tracking=True)

    # Production Details
    product_id = fields.Many2one('product.product', 'Product', required=True)
    product_qty = fields.Float('Quantity', required=True, default=1.0)
    product_uom_id = fields.Many2one('uom.uom', 'Unit of Measure')
    bom_id = fields.Many2one('mrp.bom', 'Bill of Materials')
    work_center_id = fields.Many2one('mrp.workcenter', 'Work Center')  # Fixed: using standard Odoo model

    # Smart Scheduling
    scheduling_method = fields.Selection([
        ('fcfs', 'First Come First Serve'),
        ('sjf', 'Shortest Job First'),
        ('priority', 'Priority Based'),
        ('critical_path', 'Critical Path Method'),
        ('genetic', 'Genetic Algorithm')
    ], default='priority', string='Scheduling Method')

    estimated_duration = fields.Float('Estimated Duration (Hours)', compute='_compute_estimated_duration')
    actual_duration = fields.Float('Actual Duration (Hours)')
    efficiency = fields.Float('Efficiency %', compute='_compute_efficiency')

    # Dependencies
    predecessor_ids = fields.Many2many('manufacturing.production.plan',
                                       'production_plan_dependency_rel',
                                       'successor_id', 'predecessor_id',
                                       string='Prerequisites')
    successor_ids = fields.Many2many('manufacturing.production.plan',
                                     'production_plan_dependency_rel',
                                     'predecessor_id', 'successor_id',
                                     string='Dependents')

    # Resource Requirements
    resource_requirement_ids = fields.One2many('manufacturing.resource.requirement',
                                               'production_plan_id',
                                               'Resource Requirements')

    # Progress Tracking
    progress_percentage = fields.Float('Progress %', default=0.0)
    milestone_ids = fields.One2many('manufacturing.milestone', 'production_plan_id', 'Milestones')

    # Quality & Cost
    quality_check_ids = fields.One2many('manufacturing.quality.check', 'production_plan_id', 'Quality Checks')
    estimated_cost = fields.Float('Estimated Cost', compute='_compute_estimated_cost')
    actual_cost = fields.Float('Actual Cost')

    # Analytics
    machine_utilization = fields.Float('Machine Utilization %')
    labor_utilization = fields.Float('Labor Utilization %')
    material_waste_percentage = fields.Float('Material Waste %')

    @api.model
    def create(self, vals):
        if vals.get('sequence', 'New') == 'New':
            vals['sequence'] = self.env['ir.sequence'].next_by_code('manufacturing.production.plan') or 'New'
        return super(ProductionPlan, self).create(vals)

    _sql_constraints = [
        ('unique_name', 'unique(name)', 'Plan Number must be unique!'),
    ]

    @api.depends('bom_id', 'product_qty')
    def _compute_estimated_duration(self):
        for record in self:
            if record.bom_id:
                total_time = 0
                for operation in record.bom_id.operation_ids:
                    setup_time = operation.time_mode_batch if hasattr(operation, 'time_mode_batch') else 0
                    cycle_time = operation.time_cycle * record.product_qty if hasattr(operation, 'time_cycle') else 0
                    total_time += setup_time + cycle_time
                record.estimated_duration = total_time / 60.0
            else:
                record.estimated_duration = 0.0

    @api.depends('estimated_duration', 'actual_duration')
    def _compute_efficiency(self):
        for record in self:
            if record.actual_duration and record.estimated_duration:
                record.efficiency = (record.estimated_duration / record.actual_duration) * 100
            else:
                record.efficiency = 0.0

    @api.depends('resource_requirement_ids.total_cost')
    def _compute_estimated_cost(self):
        for record in self:
            record.estimated_cost = sum(req.total_cost for req in record.resource_requirement_ids)

    def action_confirm(self):
        self.write({'state': 'confirmed'})
        self._create_manufacturing_order()

    def action_schedule(self):
        self.write({'state': 'scheduled'})
        self._apply_scheduling_algorithm()

    def action_start_production(self):
        self.write({
            'state': 'in_progress',
            'date_start': fields.Datetime.now()
        })

    def action_complete(self):
        self.write({
            'state': 'done',
            'date_end': fields.Datetime.now(),
            'progress_percentage': 100.0
        })

    def _apply_scheduling_algorithm(self):
        method = self.scheduling_method
        if method == 'priority':
            self._priority_based_scheduling()
        elif method == 'sjf':
            self._shortest_job_first()
        elif method == 'critical_path':
            self._critical_path_method()
        else:
            self._first_come_first_serve()

    def _priority_based_scheduling(self):
        plans = self.search([('state', '=', 'confirmed')], order='priority desc, date_planned asc')
        for plan in plans:
            available_slot = self._find_available_time_slot(plan)
            if available_slot:
                plan.write({
                    'date_start': available_slot['start'],
                    'date_end': available_slot['end']
                })

    def _shortest_job_first(self):
        plans = self.search([('state', '=', 'confirmed')], order='estimated_duration asc')
        for plan in plans:
            available_slot = self._find_available_time_slot(plan)
            if available_slot:
                plan.write({
                    'date_start': available_slot['start'],
                    'date_end': available_slot['end']
                })

    def _first_come_first_serve(self):
        plans = self.search([('state', '=', 'confirmed')], order='date_planned asc')
        for plan in plans:
            available_slot = self._find_available_time_slot(plan)
            if available_slot:
                plan.write({
                    'date_start': available_slot['start'],
                    'date_end': available_slot['end']
                })

    def _critical_path_method(self):
        # Simplified critical path implementation
        self._first_come_first_serve()  # Fallback to FCFS for now

    def _find_available_time_slot(self, plan):
        start_time = plan.date_planned
        end_time = start_time + timedelta(hours=plan.estimated_duration)
        return {'start': start_time, 'end': end_time}

    def _create_manufacturing_order(self):
        """Create manufacturing order from production plan"""
        try:
            self.env['mrp.production'].create({
                'product_id': self.product_id.id,
                'product_qty': self.product_qty,
                'product_uom_id': self.product_uom_id.id or self.product_id.uom_id.id,
                'bom_id': self.bom_id.id if self.bom_id else False,
                'date_planned_start': self.date_planned,
                'origin': self.name,
            })
        except Exception as e:
            _logger.error(f"Error creating manufacturing order: {e}")
            raise UserError(_("Failed to create manufacturing order: %s") % str(e))


class ManufacturingResource(models.Model):
    """Resource model for manufacturing"""
    _name = 'manufacturing.resource'
    _description = 'Manufacturing Resource'

    name = fields.Char('Resource Name', required=True)
    resource_type = fields.Selection([
        ('machine', 'Machine'),
        ('labor', 'Labor'),
        ('tool', 'Tool'),
        ('material', 'Material')
    ], required=True)
    capacity = fields.Float('Capacity', default=1.0)
    cost_per_hour = fields.Float('Cost per Hour')
    is_active = fields.Boolean('Active', default=True)
    work_center_id = fields.Many2one('mrp.workcenter', 'Work Center')

    # Inverse relationship for resource requirements
    requirement_ids = fields.One2many('manufacturing.resource.requirement', 'resource_id', 'Requirements')


class ResourceRequirement(models.Model):
    _name = 'manufacturing.resource.requirement'
    _description = 'Resource Requirement'

    production_plan_id = fields.Many2one('manufacturing.production.plan', 'Production Plan', required=True,
                                         ondelete='cascade')
    resource_type = fields.Selection([
        ('machine', 'Machine'),
        ('labor', 'Labor'),
        ('tool', 'Tool'),
        ('material', 'Material')
    ], required=True)
    resource_id = fields.Many2one('manufacturing.resource', 'Resource')
    quantity_required = fields.Float('Quantity Required', default=1.0)
    duration_hours = fields.Float('Duration (Hours)')
    cost_per_hour = fields.Float('Cost per Hour')
    total_cost = fields.Float('Total Cost', compute='_compute_total_cost', store=True)

    @api.depends('quantity_required', 'duration_hours', 'cost_per_hour')
    def _compute_total_cost(self):
        for record in self:
            record.total_cost = record.quantity_required * record.duration_hours * record.cost_per_hour


class Milestone(models.Model):
    _name = 'manufacturing.milestone'
    _description = 'Production Milestone'

    production_plan_id = fields.Many2one('manufacturing.production.plan', 'Production Plan', required=True,
                                         ondelete='cascade')
    name = fields.Char('Milestone Name', required=True)
    description = fields.Text('Description')
    planned_date = fields.Datetime('Planned Date')
    actual_date = fields.Datetime('Actual Date')
    progress_percentage = fields.Float('Progress at Milestone')
    is_completed = fields.Boolean('Completed', default=False)
    sequence = fields.Integer('Sequence', default=10)




    def action_mark_completed(self):
        self.write({
            'is_completed': True,
            'actual_date': fields.Datetime.now()
        })
        # Update production plan progress
        self.production_plan_id._update_progress()

    def action_mark_uncompleted(self):
        self.write({
            'is_completed': False,
            'actual_date': False
        })
        self.production_plan_id._update_progress()


class QualityCheck(models.Model):
    _name = 'manufacturing.quality.check'
    _description = 'Manufacturing Quality Check'

    production_plan_id = fields.Many2one('manufacturing.production.plan', 'Production Plan', required=True,
                                         ondelete='cascade')
    name = fields.Char('Check Name', required=True)
    description = fields.Text('Description')
    check_type = fields.Selection([
        ('visual', 'Visual Inspection'),
        ('measurement', 'Measurement'),
        ('functional', 'Functional Test'),
        ('safety', 'Safety Check')
    ], required=True)
    status = fields.Selection([
        ('pending', 'Pending'),
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('na', 'Not Applicable')
    ], default='pending')
    responsible_user_id = fields.Many2one('res.users', 'Responsible')
    check_date = fields.Datetime('Check Date')
    notes = fields.Text('Notes')

    def action_mark_pass(self):
        self.write({
            'status': 'pass',
            'check_date': fields.Datetime.now()
        })

    def action_mark_fail(self):
        self.write({
            'status': 'fail',
            'check_date': fields.Datetime.now()
        })