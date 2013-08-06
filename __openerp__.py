{
   'name': 'Fnx File System',
    'version': '0.2',
    'category': 'Generic Modules',
    'description': """\
            Phoenix file management system.
            """,
    'author': 'Emile van Sebille',
    'maintainer': 'Emile van Sebille',
    'website': 'www.openerp.com',
    'depends': [
            'base',
            'fnx',
        ],
    'js': [
        ],
    'update_xml': [
            'security/security.xml',
            'security/ir.model.access.csv',
            'res_config_view.xml',
            'fs_view.xml',
        ],
    'test': [],
    'installable': True,
    'active': False,
}
