{
    'name': 'Clinic & Hospital Management',
    'version': '19.0.1.0.0',
    'category': 'Services/Clinic',
    'summary': 'Patients, appointments, OPD, IPD, beds, pharmacy, laboratory and billing',
    'description': """
Clinic & Hospital Management
============================
A simple, complete clinic ERP built on standard Odoo:

* Interactive dashboard with live KPIs and charts
* Patients, doctors and staff with role-based access
* Appointments with conflict checks and OPD consultations
* Inpatient admissions, room & bed management and discharges
* Prescriptions linked to Inventory, laboratory requests and reports
* Invoicing through standard Odoo Accounting
    """,
    'author': 'EBITDA SOLUTIONS LLP',
    'website': 'https://ebitdasolutions.com',
    'license': 'LGPL-3',
    'maintainers': ['EBITDA SOLUTIONS LLP'],
    'price': 100,
    'currency': 'USD',
    'depends': ['mail', 'product', 'stock', 'account'],
    'data': [
        'security/clinic_security.xml',
        'security/ir.model.access.csv',
        'data/clinic_sequence_data.xml',
        'data/clinic_data.xml',
        'report/clinic_report_actions.xml',
        'report/clinic_report_templates.xml',
        'views/clinic_dashboard_views.xml',
        'views/clinic_patient_views.xml',
        'views/clinic_doctor_views.xml',
        'views/clinic_staff_views.xml',
        'views/clinic_appointment_views.xml',
        'views/clinic_consultation_views.xml',
        'views/clinic_room_views.xml',
        'views/clinic_admission_views.xml',
        'views/clinic_discharge_views.xml',
        'views/clinic_prescription_views.xml',
        'views/clinic_lab_views.xml',
        'views/clinic_config_views.xml',
        'views/account_move_views.xml',
        'views/res_config_settings_views.xml',
        'views/clinic_reporting_views.xml',
        'views/clinic_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'clinic_management/static/src/dashboard/*',
        ],
    },
    'images': [
        'static/description/banner.png',
    ],
    'application': True,
    'installable': True,
}
