# -*- coding: utf-8 -*-
# from odoo import http


# class ManufacturingErpSuite(http.Controller):
#     @http.route('/manufacturing_erp_suite/manufacturing_erp_suite', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/manufacturing_erp_suite/manufacturing_erp_suite/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('manufacturing_erp_suite.listing', {
#             'root': '/manufacturing_erp_suite/manufacturing_erp_suite',
#             'objects': http.request.env['manufacturing_erp_suite.manufacturing_erp_suite'].search([]),
#         })

#     @http.route('/manufacturing_erp_suite/manufacturing_erp_suite/objects/<model("manufacturing_erp_suite.manufacturing_erp_suite"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('manufacturing_erp_suite.object', {
#             'object': obj
#         })

