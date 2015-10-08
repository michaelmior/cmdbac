import os, sys
sys.path.append(os.path.join(os.path.dirname(__file__), os.pardir))

import logging
import re
import time
import importlib
import traceback
import MySQLdb

from basedeployer import BaseDeployer
from crawler.models import *
import utils

## =====================================================================
## LOGGING CONFIGURATION
## =====================================================================
LOG = logging.getLogger()

## =====================================================================
## SETTINGS
## =====================================================================
DJANGO_SETTINGS = """
SECRET_KEY = 'abcdefghijklmnopqrstuvwxyz'
ALLOWED_HOSTS = ['localhost', '127.0.0.1']
DATABASES = {{
    'default': {{
        'ENGINE': 'django.db.backends.mysql',
        'NAME': '{}',
        'HOST': '127.0.0.1',
        'PORT': '3306',
        'USER': 'root',
        'PASSWORD': 'root'
    }}
}}
EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'
EMAIL_FILE_PATH = '{}'
REGISTRATION_CAPTCHA = False
"""

## =====================================================================
## DJANGO DEPLOYER
## =====================================================================
class DjangoDeployer(BaseDeployer):
    def __init__(self, repo, database):
        BaseDeployer.__init__(self, repo, database)
        self.database_name = 'django_app'
    ## DEF
    
    def configure_settings(self):
        with open(self.setting_path, "a") as my_setting_file:
            my_setting_file.write(DJANGO_SETTINGS.format(self.database_name, self.deployer_path))
        ## WITH
    ## DEF
    
    def install_requirements(self, requirement_files):
        ret_packages = []
        if requirement_files:
            for requirement_file in requirement_files:
                out = utils.pip_install(requirement_file, True)
                with open(requirement_file, "r") as my_requirement_file:
                    ret_packages += my_requirement_file.readlines()
        return ret_packages
    ## DEF

    def get_urls(self):
        sys.path.append(os.path.join(os.path.dirname(self.setting_path), os.pardir))
        app_name = os.path.split(os.path.dirname(self.setting_path))[-1]
        try:
            urls_module = importlib.import_module('{}.urls'.format(app_name))
        except:
            return ['']

        urls = []
        def get_urls_rec(urllist, url):
            for entry in urllist:
                new_entry = entry.regex.pattern
                new_url = os.path.join(url, new_entry)
                if hasattr(entry, 'url_patterns'):
                    get_urls_rec(entry.url_patterns, new_url)
                else:
                    urls.append(new_url)

        get_urls_rec(urls_module.urlpatterns, '')

        urls = list(set([re.sub(r'[\^\$]', '', url) for url in urls if '?' not in url]))
        urls = sorted(urls, key=len)
        
        return urls
    ## DEF

    def get_main_url(self):
        urls = self.get_urls()
        for url in urls:
            if not url.startswith('admin/'):
                ret_url = 'http://127.0.0.1:{}/'.format(self.repo.project_type.default_port)
                ret_url = urlparse.urljoin(ret_url, url)
                return ret_url
        return None
    ## DEF

    def sync_server(self, path):
        LOG.info('Syncing server ...')
        command = '{} && {} && unset DJANGO_SETTINGS_MODULE && python manage.py syncdb --noinput'.format(
            utils.to_env(), utils.cd(path))
        return utils.run_command(command)
    ## DEF

    def create_superuser(self, path):
        LOG.info('Creating superuser ...')
        command = '{} && {} && {}'.format(
            utils.to_env(),
            utils.cd(path),
            """
            echo "from django.contrib.auth.models import User; User.objects.create_superuser('admin', 'admin@test.com', 'admin')" | python manage.py shell
            """)
        return utils.run_command(command)
    ## DEF

    def run_server(self, path):
        self.configure_network()
        LOG.info('Running server ...')
        command = '{} && {} && unset DJANGO_SETTINGS_MODULE && python manage.py runserver 0.0.0.0:{}'.format(
            utils.to_env(),
            utils.cd(path),
            self.repo.project_type.default_port)
        return utils.run_command_async(command)
    ## DEF

    def try_deploy(self, attempt, deploy_path, requirement_files):
        LOG.info('Configuring settings ...')
        self.kill_server()
        self.clear_database()
        self.configure_settings()

        attempt.database = self.get_database(self.setting_path)
        LOG.info('Database: ' + attempt.database.name)

        LOG.info('Installing requirements ...')
        packages = self.install_requirements(requirement_files)
        for package in packages:
            if len(package.split('==')) >= 2:
                name, version = package.split('==')
            elif len(package.split('>=')) >= 2:
                name, version = package.split('>=')
            else:
                name, version = package, ''
            try:
                pkg, created = Package.objects.get_or_create(name=name, version=version, project_type=self.repo.project_type)
                self.packages_from_file.append(pkg)
            except:
                print traceback.print_exc()
        ## FOR

        threshold = 20
        last_missing_module_name = ''
        index = -1
        dependencies = []
        for _ in range(threshold):
            output = self.sync_server(deploy_path)
            if output[0] != 0:
                LOG.info(output)
            else:
                LOG.info(output)
                break

            match = re.search('pip install ([a-zA-Z\-_]+)', output[2].strip())
            if match:
                package_name = match.group(1)
                output = utils.pip_install_text(package_name)
                continue
                # LOG.info('pip install output: {}'.format(output))

            split_output = output[2].strip().splitlines()
            line = split_output[-1].strip()
            match = re.search('(?<=No module named )\S+', line)
            if match:
                missing_module_name = match.group(0)
                LOG.info('Missing module: ' + missing_module_name)
                if missing_module_name == last_missing_module_name:
                    missing_module_name, candidate_packages, index = dependencies[-1]
                    index = index + 1
                    if index < len(candidate_packages):
                        dependencies[-1] = (missing_module_name, candidate_packages, index)
                        LOG.info('pip install {}'.format(candidate_packages[index]))
                        pip_output = utils.pip_install([candidate_packages[index]], False)
                        LOG.info('pip install output: {}'.format(pip_output))
                    else:
                        LOG.info('No more possible packages!')
                        return ATTEMPT_STATUS_MISSING_DEPENDENCIES
                else:
                    last_missing_module_name = missing_module_name
                    candidate_package_ids = Module.objects.filter(name=missing_module_name).values_list('package_id', flat=True)
                    if not candidate_package_ids:
                        LOG.info('No possible packages!')
                        return ATTEMPT_STATUS_MISSING_DEPENDENCIES
                    
                    candidate_packages = Package.objects.filter(id__in=candidate_package_ids).order_by('-version', '-count', 'name')
                    LOG.info('pip install {}'.format(candidate_packages[0]))
                    pip_output = utils.pip_install([candidate_packages[0]], False, False)            
                    LOG.info('pip install output: {}'.format(pip_output))
                    try:
                        version = re.search('Successfully installed .*-(.*)', pip_output[1]).group(1)
                        if any(package.version == version for package in candidate_packages):
                            for package_index in range(len(candidate_packages)):
                                if candidate_packages[package_index].version == version:
                                    candidate_packages = [candidate_packages[package_index]] + candidate_packages[:package_index] + candidate_packages[package_index + 1:]
                                    break
                        else:
                            latest_package = Package()
                            latest_package.project_type = candidate_packages[0].project_type
                            latest_package.name = candidate_packages[0].name
                            latest_package.version = version
                            latest_package.save()
                            module = Module()
                            module.name = missing_module_name
                            module.package = latest_package
                            module.save()
                            candidate_packages = list([latest_package]) + list(candidate_packages)
                    except:
                        print traceback.print_exc()
                    dependencies.append((missing_module_name, candidate_packages, 0))
            else:
                return ATTEMPT_STATUS_RUNNING_ERROR
        ## FOR

        for missing_module_name, candidate_packages, index in dependencies:
            self.packages_from_database.append(candidate_packages[index])

        self.create_superuser(deploy_path)

        self.run_server(deploy_path)
        time.sleep(5)
        attemptStatus = self.check_server(self.get_urls())

        return attemptStatus
    ## DEF
    
    def deploy_repo_attempt(self, attempt, deploy_path):
        LOG.info(utils.configure_env(self.deploy_path))

        setting_files = utils.search_file(deploy_path, 'settings.py')
        
        if not setting_files:
            for candidate_setting_files in utils.search_file(deploy_path, 'settings_example.py'):
                utils.copy_file(candidate_setting_files, os.path.join(os.path.dirname(candidate_setting_files), "settings.py"))
                break
            setting_files = utils.search_file(deploy_path, 'settings.py')
        
        if not setting_files:
            for candidate_setting_files in utils.search_file_regex(deploy_path, '^settings.*\.py$'):
                utils.copy_file(candidate_setting_files, os.path.join(os.path.dirname(candidate_setting_files), "settings.py"))
                break
            setting_files = utils.search_file(deploy_path, 'settings.py')
        
        if not setting_files:
            return ATTEMPT_STATUS_NOT_AN_APPLICATION, None

        # LOG.info('settings.py: {}'.format(setting_files))

        manage_files = utils.search_file(deploy_path, 'manage.py')
        # LOG.info('manage.py: {}'.format(manage_files))
        if not manage_files:
            return ATTEMPT_STATUS_MISSING_REQUIRED_FILES, None

        requirement_files = utils.search_file(deploy_path, 'requirements.txt')
        # LOG.info('requirements.txt: {}'.format(requirement_files))
        
        manage_paths = [os.path.dirname(manage_file) for manage_file in manage_files]
        
        base_dir = next(name for name in manage_paths)
        
        manage_path = next(name for name in manage_paths if name.startswith(base_dir))
        setting_file = next(name for name in setting_files if name.startswith(base_dir))
        
        self.setting_path = setting_file

        attempt.base_dir = base_dir.split('/', 1)[1]
        # LOG.info('BASE_DIR: ' + attempt.base_dir)
        
        attempt.setting_dir = os.path.basename(os.path.dirname(setting_file))
        # LOG.info('SETTING_DIR: ' + attempt.setting_dir)
        
        return self.try_deploy(attempt, manage_path, requirement_files)
    ## DEF
    
## CLASS
