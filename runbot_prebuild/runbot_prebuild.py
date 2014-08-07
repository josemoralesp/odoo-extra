# -*- encoding: utf-8 -*-
#TODO: license from vauxoo
from openerp.osv import fields, osv
import os
import shutil
import logging
import glob
import time
from openerp.addons.runbot.runbot import RunbotController

_logger = logging.getLogger(__name__)

def mkdirs(dirs):
    for d in dirs:
        if not os.path.exists(d):
            os.makedirs(d)

class runbot_prebuild_branch(osv.osv):
    _name = "runbot.prebuild.branch"
    _rec_name = 'branch_id'

    _columns = {
        'branch_id': fields.many2one('runbot.branch', 'Modules branch', required=True,
            ondelete='cascade', select=1),
        'check_pr': fields.boolean('Check PR',
            help='If is True, this will check Pull Request for this branch in this prebuild'),
        'sha_commit': fields.char('SHA commit', size=40,
            help='Empty=Currently version\nSHA=Get this version in builds'),
        'prebuild_id': fields.many2one('runbot.prebuild', 'Pre-Build', required=True,
            ondelete='cascade', select=1),
        'repo_id': fields.related('branch_id', 'repo_id', type="many2one",
            relation="runbot.repo", string="Repository", readonly=True, store=True,
            ondelete='cascade', select=1),
    }


class runbot_prebuild(osv.osv):
    _name = "runbot.prebuild"

    _columns = {
        'name': fields.char("Name", size=128, required=True),
        'main_branch_id': fields.many2one('runbot.branch', 'Main branch', required=True,
            ondelete='cascade', select=1),
        'module_branch_ids': fields.one2many('runbot.prebuild.branch', 'prebuild_id',
            string='Branches of modules', copy=True,
            help="Community addons branches which need to run tests."),
        'repo_id': fields.related('main_branch_id', 'repo_id', type="many2one",
            relation="runbot.repo", string="Repository from main branch", readonly=True,
            store=True, ondelete='cascade', select=1),
        'sticky': fields.boolean('Sticky', select=1,
            help="If True: Stay alive a instance ever. And check PR to main branch and"\
            " modules branches for make pre-builds\nIf False: Stay alive a instance only"\
            " moment and not check PR."),
        'modules': fields.char("Modules to Install", size=256,
            help="Empty is all modules availables"),
        'modules_to_exclude': fields.char("Modules to exclude", size=256,
            help="Empty is exclude none. Add modules is exclude this one. FEATURE TODO"),
        'language': fields.char("Language of instance", size=5,
            help="Language to change instance after of run test.\nFormat ll_CC<-language and country"),
        'script_prebuild': fields.text('Script Pre-Build',
            help="Script to execute before run build"),
        'script_posbuild': fields.text('Script Pos-Build',
            help="Script to execute after run build"),
    }

    def create_build(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        repo_obj = self.pool.get('runbot.repo')
        build_obj = self.pool.get('runbot.build')
        build_ids = []
        for prebuild in self.browse(cr, uid, ids, context=context):
            main_repository = prebuild.main_branch_id.repo_id
            module_repositories = [prebuild_branch.branch_id.repo_id for prebuild_branch in prebuild.module_branch_ids]

            #Update repository but no create default build
            context.update({'create_builds': False})
            repo_obj.update_git(cr, uid, main_repository, context=context)
            for prebuild_branch in prebuild.module_branch_ids:
                repo_obj.update_git(cr, uid, prebuild_branch.branch_id.repo_id, prebuild=prebuild, context=context)

            build_info = {
                'branch_id': prebuild.main_branch_id.id,
                'name': prebuild.name,#TODO: Get this value
                'author': prebuild.name,#TODO: Get this value
                'subject': prebuild.name,#TODO: Get this value
                'date': time.strftime("%Y-%m-%d %H:%M:%S"),#TODO: Get this value
                'modules': prebuild.modules,

                'prebuild_id': prebuild.id,#Important field for custom build and custom checkout
            }
            build_id = build_obj.create(cr, uid, build_info)
            build_ids.append( build_id )
        return build_ids

class runbot_branch(osv.osv):
    _inherit = "runbot.branch"

    def name_get(self, cr, uid, ids, context=None):
        if isinstance(ids, (list, tuple)) and not len(ids):
            return []
        if isinstance(ids, (long, int)):
            ids = [ids]
        res_name = super(runbot_branch, self).name_get(cr, uid, ids, context=context)
        res = []
        for record in res_name:
            branch = self.browse(cr, uid, [record[0]], context=context)[0]
            name = '[' + record[1] + '] ' + branch.repo_id.name
            res.append((record[0], name))
        return res

class runbot_build(osv.osv):
    _inherit = "runbot.build"

    _columns = {
        'prebuild_id': fields.many2one('runbot.prebuild', string='Runbot Pre-Build',
            required=False, help="This is the origin of instance data."),
    }

    def force_schedule(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        context.update({'build_ids': ids})
        build_obj = self.pool.get('runbot.repo')
        return build_obj.scheduler(cr, uid, ids=None, context=context)

    def checkout_params(self, cr, uid, ids, main_branch_id, module_branch_ids, modules_to_test=None, context=None):
        branch_obj = self.pool.get('runbot.branch')
        main_branch = branch_obj.browse(cr, uid, [main_branch_id], context=context)[0]
        for build in self.browse(cr, uid, ids, context=context):
            # starts from scratch
            if os.path.isdir(build.path()):
                shutil.rmtree(build.path())
            _logger.debug('Creating build in path "%s"'%( build.path() ))

            # runbot log path
            mkdirs([build.path("logs"), build.server('addons')])

            # checkout main branch
            #TODO: main_branch.name or sha_commit
            main_branch.repo_id.git_export(main_branch.name, build.path())

            # TODO use git log to get commit message date and author

            # v6 rename bin -> openerp
            if os.path.isdir(build.path('bin/addons')):
                shutil.move(build.path('bin'), build.server())

            # move all addons to server addons path
            for module in glob.glob( build.path('addons/*') ):
                shutil.move(module, build.server('addons'))

            if module_branch_ids:
                for module_branch in branch_obj.browse(cr, uid, module_branch_ids, context=context):
                    #TODO: main_branch.name or sha_commit
                    module_branch.repo_id.git_export(module_branch.name, build.server("addons"))
                    #Note: If a module name is duplicate no make error. TODO: But is good make a log.info.
            """#This funtion there is into cmd function
            if not modules_to_test:
                #Find modules to test from the folder branch
                modules_to_test = ','.join(
                    os.path.basename(os.path.dirname(module_openerp))
                    for module_openerp in glob.glob(build.path('*/__openerp__.py'))
                )
            """
            build.write({'modules': modules_to_test})

    def checkout(self, cr, uid, ids, context=None):
        for build in self.browse(cr, uid, ids, context=context):
            if not build.prebuild_id:
                #TODO: Split branches for use same function "checkout_params"
                return super(runbot_build, self).checkout(cr, uid, ids, context=context)
            else:
                main_branch_id = build.prebuild_id.main_branch_id.id
                module_branch_ids = [module_branch_id.branch_id.id for module_branch_id in build.prebuild_id.module_branch_ids]
                self.checkout_params(cr, uid, [build.id], main_branch_id=main_branch_id, module_branch_ids=module_branch_ids, modules_to_test=build.prebuild_id.modules, context=context)



class RunbotController(RunbotController):

    def build_info(self, build):
        res = super(RunbotController, self).build_info(build)
        res.update({'prebuild_id':build.prebuild_id,
                    'build':build})
        return res


