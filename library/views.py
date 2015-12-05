import os, sys
sys.path.append(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.append(os.path.join(os.path.dirname(__file__), os.pardir, "core"))

import traceback
import markdown
from threading import Thread
 
from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.decorators import detail_route
from rest_framework.response import Response
from serializers import AttemptSerializer
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib import messages
from django.shortcuts import redirect, get_object_or_404
from django.db.models import Count
from models import *
from forms import *
import utils

class Statistic:
    def __init__(self, repo_type, num_repo, num_suc, num_deploy, num_valid_deploy):
        self.repo_type = repo_type
        self.num_repo = num_repo
        self.num_suc = num_suc
        self.num_deploy = num_deploy
        self.num_valid_deploy = num_valid_deploy
        if self.num_valid_deploy == 0:
            self.suc_rate = 0
        else:
            self.suc_rate = int(self.num_suc * 100 / self.num_valid_deploy)

def home(request):
    context = {}
    stats = []
    for t in ProjectType.objects.all():
        repo_type = t.name
        repos = Repository.objects.filter(project_type=t)
        num_repo = repos.count()
        num_suc = repos.filter(latest_attempt__result=ATTEMPT_STATUS_SUCCESS).count()
        # num_pkg = Package.objects.filter(project_type=t).count()
        num_deploy = repos.exclude(latest_attempt=None).count()
        num_valid_deploy = repos.filter(valid_project=True).count()
        stat = Statistic(repo_type, num_repo, num_suc, num_deploy, num_valid_deploy)
        stats.append(stat)
    context['stats'] = stats
    context['attempts'] = Attempt.objects.exclude(result=ATTEMPT_STATUS_MISSING_REQUIRED_FILES).order_by('-start_time')[:5]
    return render(request, 'index.html', context)

def repositories(request):
    context = {}
    context['queries'] = request.GET.copy()

    queries_no_page = request.GET.copy()
    if queries_no_page.__contains__('page'):
        del queries_no_page['page']
    if queries_no_page.__contains__('search') and queries_no_page['search'] == '':
        del queries_no_page['search']
    context['queries_no_page'] = queries_no_page

    queries_no_page_order = queries_no_page.copy() 
    if queries_no_page_order.__contains__('order_by'):
        context['order_by'] = request.GET.get('order_by')
        del queries_no_page_order['order_by']
    context['queries_no_page_order'] = queries_no_page_order

    context["result_form"] = ResultForm(request.GET)
    context['type_form'] = ProjectTypeForm(request.GET)


    if request.user.is_superuser:
        if request.GET.__contains__('module') and request.GET.__contains__('package') and request.GET.__contains__('type') and request.GET.__contains__('version'):
            module_name = request.GET['module']
            package_name = request.GET['package']
            package_type = request.GET['type']
            package_version = request.GET['version']
            print 'add ' + package_type + ' module : ' + module_name
            project_type_map = {'django': 1, 'ror': 2}
            try:    
                utils.add_module(module_name, package_name, project_type_map[package_type], package_version)
                messages.success(request, 'Successfully added new module {}'.format(module_name))
            except:
                messages.error(request, 'Failed to add new module {}'.format(repo_name))
                traceback.print_exc()
            finally:
                return redirect(request.META['HTTP_REFERER'])

        if request.GET.__contains__('repo') and request.GET.__contains__('type'):
            repo_name = request.GET['repo']
            repo_type = request.GET['type']
            repo_setup_scripts = request.GET['scripts']
            print 'add ' + repo_type + ' repository : ' + repo_name
            project_type_map = {'django': 1, 'ror': 2, 'node': 3}
            try:    
                utils.add_repo(repo_name, project_type_map[repo_type], repo_setup_scripts)
                messages.success(request, 'Successfully added new repository {}'.format(repo_name))
            except:
                messages.error(request, 'Failed to add new repository {}'.format(repo_name))
                traceback.print_exc()
            finally:
                return redirect(request.META['HTTP_REFERER'])

        if request.GET.__contains__('deploy'):
            repo_name = request.GET['deploy']
            print 'deploy: ' + repo_name
            try:
                thread = Thread(target = utils.deploy_repo, args = (repo_name, ))
                thread.start()
                # thread.join()
                messages.success(request, 'Deploying repository {}'.format(repo_name))
            except:
                messages.error(request, 'Failed to deploy repository {}'.format(repo_name))
                traceback.print_exc()
            finally:
                return redirect(request.META['HTTP_REFERER'])

        if request.GET.__contains__('delete'):
            repo_name = request.GET['delete']
            print 'delete: ' + repo_name
            try:
                utils.delete_repo(repo_name)
                messages.success(request, 'Successfully deleted repository {}'.format(repo_name))
            except:
                messages.error(request, 'Failed to delete repository {}'.format(repo_name))
                traceback.print_exc()
            finally:
                return redirect(request.META['HTTP_REFERER'])

    repositories = Repository.objects.all()
    if request.GET.get('search', '') != '':
        repo_name = request.GET['search']
        print 'search: ' + repo_name
        context['search'] = repo_name
        repositories = repositories.filter(name__contains=repo_name)

    result_list = request.GET.getlist('results')
    if result_list:
        repositories = repositories.filter(latest_attempt__result__in=result_list)

    type_list = request.GET.getlist('types')
    if type_list:
        repositories = repositories.filter(project_type__name__in=type_list)

    order_by = request.GET.get('order_by', 'crawler_date')
    repositories = repositories.order_by(order_by)

    paginator = Paginator(repositories, 50) # Show 50 repos per page
    page = request.GET.get('page')
    try:
        repositories = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        repositories = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        repositories = paginator.page(paginator.num_pages)
        
    context["repositories"] = repositories

    return render(request, 'repositories.html', context)

def repository(request, user_name, repo_name):
    context = {}
    context['queries'] = request.GET.copy()
    
    repository = Repository.objects.get(name=user_name + '/' + repo_name)
    context['repository'] = repository

    attempts = Attempt.objects.filter(repo=repository).order_by("-id")
    paginator = Paginator(attempts, 50) # Show 50 repos per page
    page = request.GET.get('page')
    try:
        attempts = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        attempts = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        attempts = paginator.page(paginator.num_pages)
    context['attempts'] = attempts
    
    return render(request, 'repository.html', context)

def attempt(request, id):
    context = {}
    
    context['queries'] = request.GET.copy()

    attempt = Attempt.objects.get(id=id)
    context['attempt'] = attempt

    dependencies = Dependency.objects.filter(attempt__id=id).order_by('package__name')
    context['dependencies'] = dependencies
    
    forms = Form.objects.filter(attempt=attempt)
    context['forms'] = []
    for form in forms:
        fields = Field.objects.filter(form=form)
        counters = Counter.objects.filter(form=form)
        keyword_order = {
            'SELECT': 1,
            'INSERT': 2,
            'UPDATE': 3,
            'DELETE': 4
        }
        counters = sorted(counters, key = lambda x: keyword_order.get(x.description, 10))
        context['forms'].append({
            'id': form.id,
            'action': form.action,
            'url': form.url,
            'fields': fields,
            'counters': counters
        })
    
    try:
        image = Image.objects.get(attempt=attempt)
        screenshot_filename = 'screenshot_{}.png'.format(attempt.id)
        screenshot = open(os.path.join(os.path.dirname(__file__), 'static', screenshot_filename), 'wb')
        screenshot.write(image.data)
        screenshot.close()
        context['screenshot'] = '/static/' + screenshot_filename
    except:
        pass

    return render(request, 'attempt.html', context)

def queries(request, id):
    if request.is_ajax():
        context = {}

        form = Form.objects.get(id=id)
        queries = Query.objects.filter(form=form)
        context['form'] = {
            'id': form.id,
            'queries': queries
        }
        
        return render(request, 'queries.html', context)

def people(request):
    return render(request, 'people.html')

def tools(request):
    context = {}
    content = open(os.path.join(os.path.dirname(__file__), 'static', 'md', 'tools.md'), 'r').read()
    context['content'] = markdown.markdown(content, extensions = ['markdown.extensions.fenced_code'])
    return render(request, 'tools.html', context)

class AttemptViewSet(viewsets.ViewSet):
    def get_queryset(self):
        return Attempt.objects.all()

    @detail_route(methods=['get'])
    def detail(self, request, pk):
        queryset = Attempt.objects.all()
        attempt = get_object_or_404(queryset, id=pk)
        serializer = AttemptSerializer(attempt)
        return Response(serializer.data)

    @detail_route(methods=['post'])
    def benchmark(self, request, pk):
        queryset = Attempt.objects.all()
        attempt = get_object_or_404(queryset, id=pk)
        serializer = AttemptSerializer(attempt)

        # check payload
        payload = dict(request.data)
        print payload
        if 'database' not in payload and 'benchmark' not in payload:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        # run benchmark
        utils.run_benchmark(pk, payload['database'], payload['benchmark'])

        return Response({'status': 'password set'})