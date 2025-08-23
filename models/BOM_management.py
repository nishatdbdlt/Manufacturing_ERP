from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)






class EngineeringChange(models.Model):
    _name = 'manufacturing.engineering.change'
    _description = 'Engineering Change Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('ECO Number', required=True)
    bom_id = fields.Many2one('mrp.bom', 'BOM', required=True)
    change_type = fields.Selection([
        ('addition', 'Component Addition'),
        ('removal', 'Component Removal'),
        ('modification', 'Component Modification'),
        ('process', 'Process Change')
    ], required=True)

    description = fields.Text('Change Description', required=True)
    reason = fields.Text('Reason for Change')
    impact_analysis = fields.Text('Impact Analysis')

    requested_by = fields.Many2one('res.users', 'Requested By', default=lambda self: self.env.user)
    approved_by = fields.Many2one('res.users', 'Approved By')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('review', 'Under Review'),
        ('approved', 'Approved'),
        ('implemented', 'Implemented'),
        ('rejected', 'Rejected')
    ], default='draft', tracking=True)

    effective_date = fields.Date('Effective Date')
    cost_impact = fields.Float('Cost Impact')


class BOMManagement(models.Model):
    _inherit = 'mrp.bom'

    # Version Control
    version = fields.Char('Version', default='1.0')
    parent_bom_id = fields.Many2one('mrp.bom', 'Parent BOM')
    child_bom_ids = fields.One2many('mrp.bom', 'parent_bom_id', 'Child BOMs')

    # Engineering Changes
    engineering_change_ids = fields.One2many('manufacturing.engineering.change', 'bom_id', 'Engineering Changes')
    approval_status = fields.Selection([
        ('draft', 'Draft'),
        ('review', 'Under Review'),
        ('approved', 'Approved'),
        ('obsolete', 'Obsolete')
    ], default='draft')

    # Cost Analysis
    material_cost = fields.Float('Material Cost', compute='_compute_costs')
    labor_cost = fields.Float('Labor Cost', compute='_compute_costs')
    overhead_cost = fields.Float('Overhead Cost', compute='_compute_costs')
    total_cost = fields.Float('Total Cost', compute='_compute_costs')

    # Advanced Features
    complexity_score = fields.Float('Complexity Score', compute='_compute_complexity')
    sustainability_score = fields.Float('Sustainability Score')
    # Fixed: Added explicit relation table name for self-referential Many2many
    # alternate_bom_ids = fields.Many2many(
    #     'mrp.bom',
    #     relation='mrp_bom_alternate_rel',  # Explicit relation table name
    #     column1='bom_id',                   # Column for current record
    #     column2='alternate_bom_id',         # Column for related record
    #     string='Alternate BOMs'
    # )

    # Quality Requirements
    # quality_specification_ids = fields.One2many('manufacturing.quality.specification', 'bom_id',
    #                                             'Quality Specifications')

    @api.depends('bom_line_ids', 'operation_ids')
    def _compute_costs(self):
        for bom in self:
            material_cost = sum(line.product_qty * line.product_id.standard_price for line in bom.bom_line_ids)
            labor_cost = sum(op.time_cycle * op.workcenter_id.costs_hour / 60 for op in bom.operation_ids)
            overhead_cost = (material_cost + labor_cost) * 0.2

            bom.material_cost = material_cost
            bom.labor_cost = labor_cost
            bom.overhead_cost = overhead_cost
            bom.total_cost = material_cost + labor_cost + overhead_cost

    @api.depends('bom_line_ids', 'operation_ids')
    def _compute_complexity(self):
        for bom in self:
            component_complexity = len(bom.bom_line_ids) * 1.0
            operation_complexity = len(bom.operation_ids) * 1.5
            level_complexity = bom._get_bom_levels() * 2.0
            bom.complexity_score = component_complexity + operation_complexity + level_complexity

    def _get_bom_levels(self):
        max_level = 0
        for line in self.bom_line_ids:
            if line.product_id.bom_ids:
                child_level = line.product_id.bom_ids[0]._get_bom_levels()
                max_level = max(max_level, child_level + 1)
        return max_level


class EngineeringChange(models.Model):
    _name = 'manufacturing.engineering.change'
    _description = 'Engineering Change Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('ECO Number', required=True)
    bom_id = fields.Many2one('mrp.bom', 'BOM', required=True)
    change_type = fields.Selection([
        ('addition', 'Component Addition'),
        ('removal', 'Component Removal'),
        ('modification', 'Component Modification'),
        ('process', 'Process Change')
    ], required=True)

    description = fields.Text('Change Description', required=True)
    reason = fields.Text('Reason for Change')
    impact_analysis = fields.Text('Impact Analysis')

    requested_by = fields.Many2one('res.users', 'Requested By', default=lambda self: self.env.user)
    approved_by = fields.Many2one('res.users', 'Approved By')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('review', 'Under Review'),
        ('approved', 'Approved'),
        ('implemented', 'Implemented'),
        ('rejected', 'Rejected')
    ], default='draft', tracking=True)

    effective_date = fields.Date('Effective Date')
    cost_impact = fields.Float('Cost Impact')