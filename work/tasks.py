#
# Codasip s.r.o.
#
# CONFIDENTIAL
#
# Copyright 2019 Codasip s.r.o.
#
# All Rights Reserved.
#
# NOTICE: All information contained in this file, is and shall remain the property of
# Codasip s.r.o. and its suppliers, if any.
#
# The intellectual and technical concepts contained herein are confidential and proprietary to
# Codasip s.r.o. and are protected by trade secret and copyright law.  In addition, elements of the
# technical concepts may be patent pending.
#
# This file is part of the Codasip Studio product. No part of the Studio product, including this
# file, may be use, copied, modified, or distributed except in accordance with the terms contained
# in Codasip license agreement under which you obtained this file.
#

import copy
import fnmatch
import os
import zipfile
from functools import partial

import codasip.build.configuration
import codasip.build.dk_models
import codasip.build.project
import codasip.tasks as tasks
import codasip.testsuite.hdk
import codasip.testsuite.sdk
import codasip.utility.decorators
import codasip.utility.filter_decorator
import codasip.utility.internal
import codasip.utility.logger
import codasip.utility.preprocessor
import codasip.utility.utils


####################################################################################################
def sdk_generator(task_generator):
    """Task decorator that modifies all tasks generating SDK tools.

    It will add another action to the task that will refresh the XML describing an SDK.
    It will also add _sdk_tools task as dependency for all decorated tasks.
    """

    @codasip.utility.decorators.wraps(task_generator)
    def _wrapper(*args):
        model = args[0]
        sdk_id = model.config['sdk-id']

        def refresh_sdk():
            """Task action to recreate SDK XML"""
            sdk = codasip.testsuite.sdk.SdkXml(model.sdk.dir)
            sdk.add_model(model.sdk)
            sdk.save(custom_id=sdk_id)

        def modify_task(task):
            """Modify the task"""
            if task and task['basename'] != '_sdk_tools':

                # actions can be None
                if not task.get('actions'):
                    task['actions'] = [refresh_sdk]
                else:
                    task['actions'].append(refresh_sdk)

                # str is needed, because SDK ID can be None
                task.setdefault('uptodate', []).append(codasip.utility.utils.config_changed(str(sdk_id)))

                if model.ia:
                    task.setdefault('task_dep', []).append(model.get_task_id('_sdk_tools'))

            return task

        # go through all generated tasks from single task generator and modify them
        tasks = task_generator(*args)
        # from generators returning generators get list of tasks
        for task in codasip.utility.utils.flaten_generator(tasks):
            yield modify_task(task)

    return _wrapper


####################################################################################################
def hdk_generator(task_generator):
    """
    Task decorator that modifies all tasks generating HDK. Adds _hdk_tools task as dependency.
    Generate task for CA top-level models only.
    """

    @codasip.utility.decorators.wraps(task_generator)
    def _wrapper(*args):
        model = args[0]

        # only CA toplevel models
        if model.ia or not model:
            return

        hdk_id = model.config['hdk-id']

        def refresh_hdk():
            """Task action to recreate HDK XML"""
            hdk = codasip.testsuite.hdk.HdkXml(model.hdk.dir)
            hdk.add_model(model.hdk)
            hdk.save(custom_id=hdk_id)

        def modify_task(task):
            """Modify the task"""
            if task and task['basename'] != '_hdk_tools':

                # actions can be None
                if not task.get('actions'):
                    task['actions'] = [refresh_hdk]
                else:
                    task['actions'].append(refresh_hdk)

                # str is needed, because HDK ID can be None
                task.setdefault('uptodate', []).append(codasip.utility.utils.config_changed(str(hdk_id)))
                task.setdefault('task_dep', []).append(model.get_task_id('_hdk_tools'))
            return task

        # go through all generated tasks from single task generator and modify them
        tasks = task_generator(*args)
        # from generators returning generators get list of tasks
        for task in codasip.utility.utils.flaten_generator(tasks):
            yield modify_task(task)

    return _wrapper


@codasip.utility.decorators.hook(event='tasks_finished')
def add_configuration_title(event, project, task_list):
    """Automatically add current model configuration string into CodAL compilation task title.

    :param project: Instance of project.
    :type project: ~codasip.build.project.CodalProject
    :param task_list: List of tasks.
    :type task_list: list
    """
    models = {}
    for m in project.list_models():
        models[m.id] = m

    for task in task_list:
        # split tasks for models, will fail on group task
        try:
            basename, id = task.name.split(':')
        except ValueError:
            continue
        # filter to CodAL compilation tasks only
        if not basename.startswith('model.'):
            continue
        # find model by design path
        model = models.get(id)
        if model is None:
            continue
        # calculate configuration string of the model
        config = model.project.options.get_configuration()
        if not config:
            continue
        # replace task title
        name = ' {} '.format(model.id)
        changed = name + '({}) '.format(config)
        task.doc = task.doc.replace(name, changed)
        task.custom_title = lambda _: task.doc


####################################################################################################
def task_model(model):
    """"Compile model.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    compiler = tasks.CodalCompilerBuilder(model)

    def title(task):
        return 'Model Compilation'

    return {
        'basename': 'model',
        'actions': [compiler.run],
        'targets': compiler.targets,
        'file_dep': compiler.file_dep,
        'uptodate': [codasip.utility.utils.config_changed(compiler.uptodate)],
        'title': title
    }


@codasip.utility.filter_decorator.filter(sdk=True)
@sdk_generator
def task_sdk_tools(model):
    """"Generate SDK tools.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    copy_sdk = tasks.CopySdkBuilder(model)

    def title(task):
        return 'SDK Tools'

    return {
        # starts with underscore -> hidden/private tasks
        'basename': '_sdk_tools',
        'actions': [(copy_sdk.run, [])],
        'targets': copy_sdk.targets,
        'file_dep': copy_sdk.file_dep,
        'uptodate': [codasip.utility.utils.config_changed(copy_sdk.uptodate)],
        'title': title
    }


@hdk_generator
def task_hdk_tools(model):
    """"Generate HDK tools. Copy ElfConvert binaries and support files to HDK.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    # dictionary of source path -> target path
    files = {}

    # binary
    sources = []
    if codasip.HDL_TB_AUTO in model.config['rtl.testbenches']:
        sources = ['elfconvert' + codasip.utility.utils.get_exe_extension()]

    root = os.path.join(codasip.tools_dir, 'bin')
    bin_dir = os.path.join(model.hdk_dir, 'bin')
    contrib_dir = os.path.join(model.hdk_dir, 'contrib')

    # create mapping of source paths -> target ones
    for f in sources:
        files[os.path.join(root, f)] = os.path.join(model.hdk_dir, 'bin', f)

    # solve contrib directory
    required_libs_src = codasip.utility.utils.get_required_shared_libs(files.keys())
    required_libs_dst = [os.path.join(contrib_dir, os.path.basename(f)) for f in required_libs_src]
    libs_contrib = zip(required_libs_src, required_libs_dst)
    # make sure there are no duplicities in the list of target files - safety, should not happen
    required_libs_dst_uniq = list(set(required_libs_dst))

    def copy_hdk_tools(files):
        for source, target in files.items():
            target_dir = os.path.dirname(target)
            if not os.path.isdir(target_dir):
                codasip.utility.utils.makedirs(target_dir)
            codasip.utility.utils.copyfile(source, target)

    def copy_contrib(bin_dir, contrib_dir):
        codasip.utility.utils.copy_required_shared_libs(bin_dir, contrib_dir)

    def title(task):
        return 'HDK Tools'

    return {
        # starts with underscore -> hidden/private tasks
        'basename': '_hdk_tools',
        'actions': [(copy_hdk_tools, [files]), (copy_contrib, [bin_dir, contrib_dir])],
        'targets': list(files.values()) + required_libs_dst_uniq,
        'file_dep': list(files.keys()),
        'uptodate': [True],
        'title': title
    }


@codasip.utility.filter_decorator.filter(sdk=True)
@sdk_generator
def task_asm(model):
    """"Generate assembler.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """

    # do not generate CA assembler when there is IA assembler present
    if not model.ia and model.get_sibling_model(True):
        return

    asm = tasks.AssemblerBuilder(model)
    task_dep = ['_backend']

    def title(task):
        return 'Assembler'

    return {
        'basename': 'asm',
        'actions': [(asm.run)],
        'file_dep': asm.file_dep,
        'uptodate': [codasip.utility.utils.config_changed(asm.uptodate)],
        'task_dep': [model.get_task_id(t) for t in task_dep],
        'targets': asm.targets,
        'title': title
    }


@codasip.utility.filter_decorator.filter()
@sdk_generator
def task_generate_dsm(model):
    """"Generate disassembler.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    # do not generate CA disssembler when there is IA disssembler present
    if not model.ia and model.get_sibling_model(True):
        return

    dsm = tasks.DisassemblerBuilder(model)
    task_dep = ['_backend']

    def title(task):
        return 'Disassembler'

    return {
        'basename': 'dsm',
        'actions': [(dsm.run)],
        'file_dep': dsm.file_dep,
        'uptodate': [codasip.utility.utils.config_changed(dsm.uptodate)],
        'task_dep': [model.get_task_id(t) for t in task_dep],
        'targets': dsm.targets,
        'title': title
    }


@sdk_generator
def task_generate_prof(model):
    """"Generate profiler.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """

    profiler = tasks.ProfilerBuilder(model)
    ia_model = model.get_sibling_model(ia=True).filter_model()
    dsm_task = ia_model.get_task_id('dsm')

    def title(task):
        return 'Profiler'

    # basic dict common to everything
    task = {
        'actions': [profiler.run],
        'basename': 'prof',
        'uptodate': [codasip.utility.utils.config_changed(profiler.uptodate)],
        'targets': profiler.targets,
        'task_dep': [dsm_task],
        'file_dep': profiler.file_dep,
        'title': title
    }
    return task


@sdk_generator
def task_generate_sim(model):
    """"Generate simulator.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    sim = tasks.SimulatorBuilder(model)
    ia_model = model.get_sibling_model(ia=True).filter_model()
    dsm_task = ia_model.get_task_id('dsm')

    def title(task):
        return 'Simulator'

    task = {
        'actions': [sim.run],
        'basename': 'sim',
        'targets': sim.targets + sim.rsp_path,
        'file_dep': sim.file_dep,
        'task_dep': [dsm_task],
        'uptodate': [codasip.utility.utils.config_changed(sim.uptodate)],
        'title': title
    }
    return task


@sdk_generator
def task_generate_dbg(model):
    """"Generate debugger.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """

    dbg = tasks.DebuggerBuilder(model)
    ia_model = model.get_sibling_model(ia=True).filter_model()
    dsm_task = ia_model.get_task_id('dsm')

    def title(task):
        return 'Debugger'

    task = {
        'basename': 'dbg',
        'actions': [dbg.run],
        'targets': dbg.targets,
        'file_dep': dbg.file_dep,
        'task_dep': [model.get_task_id('sim'), dsm_task],
        'uptodate': [codasip.utility.utils.config_changed(dbg.uptodate)],
        'title': title,
    }
    return task


@codasip.utility.filter_decorator.filter(sdk=True, parametrize=codasip.SemanticsType)
def task_extract_semantics(model, type):
    """"Extract semantics.

    :param model: Instance of model.
    :param type: Tool type.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    semantics_extractor = tasks.SemanticsExtractorBuilder(model, type)

    def title(task):
        return semantics_extractor.title + 'semantics'

    return {
        'basename': '_semextr_' + type,
        'actions': [(semantics_extractor.run)],
        'targets': semantics_extractor.targets,
        'file_dep': semantics_extractor.file_dep,
        'uptodate': [codasip.utility.utils.config_changed(semantics_extractor.uptodate)],
        'title': title
    }


@sdk_generator
def task_generate_backend(model):
    """"Generate backend.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """

    # do not generate CA backend when there is IA backend present
    if not model.ia and model.get_sibling_model(True):
        return

    backendgen = tasks.BackendgenBuilder(model)

    def title(task):
        return 'C/C++ Backend'

    return {
        'basename': '_backend',
        'actions': [(backendgen.run)],
        'file_dep': backendgen.file_dep,
        'uptodate': [backendgen.uptodate()],
        'targets': backendgen.targets,
        'title': title
    }

@codasip.utility.filter_decorator.filter(sdk=True, compiler=True)
@sdk_generator
def task_generate_llc(model):
    """"Generate llc.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    llc = tasks.LlcBuilder(model)
    task_dep = ['_backend']

    def title(task):
        return 'llc'

    return {
        'basename': '_llc',
        'actions': [(llc.run)],
        'file_dep': llc.file_dep,
        'uptodate': [codasip.utility.utils.config_changed(llc.uptodate)],
        'task_dep': [model.get_task_id(t) for t in task_dep],
        'targets': llc.targets,
        'title': title
    }

@codasip.utility.filter_decorator.filter(sdk=True)
@sdk_generator
def task_generate_linker(model):
    """"Generate linker.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    linker = tasks.LinkerBuilder(model)

    def title(task):
        return 'Linker'

    return {
        'basename': 'linker',
        'actions': [(linker.run)],
        'file_dep': linker.file_dep,
        'uptodate': [codasip.utility.utils.config_changed(linker.uptodate)],
        'targets': linker.targets,
        'task_dep': [model.get_task_id('model')],
        'title': title
    }


@codasip.utility.filter_decorator.filter(sdk=True, compiler=True)
@sdk_generator
def task_generate_tti(model):
    """"Generate TTI library.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    ttigen = tasks.TargetTransformInfoBuilder(model)

    def title(task):
        return 'TargetTransformInfo'

    return {
        'basename': '_ttigen',
        'actions': [(ttigen.run)],
        'file_dep': ttigen.file_dep,
        'uptodate': [ttigen.uptodate],
        'targets': ttigen.targets,
        'title': title
    }


@codasip.utility.filter_decorator.filter(ia=True, compiler=True)
@sdk_generator
def task_include(model):
    """"Copy all header files from 'libs/include' to SDK.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """

    src_dir = os.path.join(model.project.dir, 'libs', 'include')
    dst_dir = os.path.join(model.sdk_dir, 'include')

    task_dep = ['_backend']
    uptodate = [codasip.utility.utils.folder_changed(src_dir, includes='*.h')]

    compiler_include_dir = os.path.join(str(model.work_dir), 'ia', 'compiler', 'compiler')
    inlines_h = os.path.join(compiler_include_dir, 'inlines.h')
    uptodate += [codasip.utility.utils.folder_changed(compiler_include_dir, includes='*.h')]

    def run():
        # clear and create output directory
        if os.path.isdir(dst_dir):
            codasip.rmtree(dst_dir, ignore_errors=True, content_only=True)
        else:
            codasip.utility.utils.makedirs(dst_dir)

        # at first copy compiler generated includes
        if os.path.exists(inlines_h):
            codasip.utility.utils.copyfile(inlines_h, dst_dir)

        if not os.path.isdir(src_dir):
            return

        # then copy all user specified includes which can override compiler generated ones
        for name in os.listdir(src_dir):
            input = os.path.join(src_dir, name)
            output = os.path.join(dst_dir, name)
            codasip.utility.utils.copy_without_options(model.project, input, output)

    def title(task):
        return 'Includes'

    return {
        'basename': '_include',
        'actions': [run],
        'task_dep': [model.get_task_id(t) for t in task_dep],
        'uptodate': uptodate,
        'title': title
    }


@codasip.utility.filter_decorator.filter(sdk=True, compiler=True)
@sdk_generator
def task_compiler(model):
    """"Generate C/C++ compiler.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """

    task_dep = ['_backend', '_include', '_llc', '_ttigen']

    def title(task):
        return 'C/C++ Compiler'

    return {
        'basename': 'compiler',
        'task_dep': [model.get_task_id(t) for t in task_dep],
        'title': title
    }


@codasip.utility.filter_decorator.filter(sdk=True, compiler=True)
@sdk_generator
def task_build_libs(model):
    """Register and generate task building included libraries.

    :param model: Instance of model.
    :rtype: generator
    """
    libs = tasks.LibrariesBuilder(model)
    backendgen = tasks.BackendgenBuilder(model)

    task_dep = ['compiler', 'asm', '_include']

    # register separate private tasks for libraries
    for f in libs.tasks:
        def title(task):
            return f.NAME + ' library, configuration string: {}'.format(f.CONFIGURATION)

        yield {
            'basename': f.task_name(),
            'actions': [f.run],
            'file_dep': f.file_dep + backendgen.file_dep,
            'targets': f.targets,
            'task_dep': [model.get_task_id(t) for t in task_dep],
            'uptodate': [codasip.utility.utils.config_changed(f.uptodate)],
            'title': title
        }

    # create main task with private dependencies

    def title(task):
        return 'SDK Libraries'

    yield ({
        'basename': 'libs',
        'actions': None,
        'task_dep': [model.get_task_id(f.task_name()) for f in libs.tasks],
        'title': title
    })


def task_sdk(model):
    """Group task to generate entire SDK.

    :param model: Instance of model
    :return: DOIT format dictionary of task
    :rtype: dict
    """
    # ASIP tasks, sim, dbg and prof has dependence on dsm task
    sdk_tasks = ['sim', 'dbg', 'prof']

    if model.ia:
        # add IA toolchain
        sdk_tasks += ['asm', 'linker']
        if model.compiler:
            sdk_tasks += ['compiler']
            # at least single SDK library is enabled
            if tasks.LibrariesBuilder(model).tasks:
                sdk_tasks += ['libs']

    # add asm and linker for CA model only when IA model is not present
    elif not model.get_sibling_model(True):
        sdk_tasks += ['asm', 'linker']

    def title(task):
        return 'SDK'

    return {
        'basename': 'sdk',
        'actions': None,  # this is just group of tasks
        'task_dep': [model.get_task_id(t) for t in sdk_tasks],
        'title': title
    }


def task_generate_cosim(model):
    """Task generating cosimulator.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """

    cosim = tasks.CosimulatorBuilder(model)
    ia_model = model.get_sibling_model(ia=True).filter_model()
    dsm_task = ia_model.get_task_id('dsm')

    def title(task):
        return cosim.COSIMULATOR_TITLE[cosim.cosim_type] + ' Co-simulator'

    # basic dict common to everything
    task = {
        'actions': [cosim.run],
        'basename': 'cosim',
        # use name from dictionary or type from configuration
        'targets': [cosim.cosim_output_dir],
        'file_dep': cosim.file_dep,
        'task_dep': [dsm_task],
        'uptodate': [codasip.utility.utils.config_changed(cosim.uptodate)],
        'title': title
    }

    return task


@codasip.utility.filter_decorator.filter(sdk=True)
def task_isa_visualization(model):
    """Task generating cosimulator.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """

    isa = tasks.IsaBuilder(model)

    def title(task):
        return 'ISA Visualization'

    # basic dict common to everything
    task = {
        'actions': [isa.run],
        'basename': 'isa',
        # use name from dictionary or type from configuration
        'targets': [isa.output_dir],
        'file_dep': isa.file_dep,
        'uptodate': [codasip.utility.utils.config_changed(isa.uptodate),
                     codasip.utility.utils.folder_changed(isa.output_dir, includes='*')],
        'title': title
    }

    return task


@codasip.utility.filter_decorator.filter(sdk=True)
def task_generate_random_asm(model):
    """Task generating random assembler programs.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    randomgen = tasks.RandomGenBuilder(model)

    sdk_tasks = ['asm', 'linker']

    def title(task):
        return 'Random assembler'

    return {
        'basename': 'random_asm',
        'actions': [randomgen.run],
        'targets': [],
        'task_dep': [model.get_task_id(t) for t in sdk_tasks],
        'file_dep': randomgen.file_dep,
        'uptodate': randomgen.uptodate,
        'title': title
    }


@codasip.utility.filter_decorator.filter(sdk=True)
def task_generate_doc(model):
    """Task generating documentation.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    docs = tasks.DocumentationBuilder(model)

    def title(task):
        return 'Documentation'

    return {
        'basename': 'doc',
        'actions': [docs.run],
        'targets': [],
        'file_dep': docs.file_dep,
        'uptodate': [codasip.utility.utils.config_changed(docs.uptodate),
                     codasip.utility.utils.folder_changed(docs.output_dir, includes='*')],
        'title': title
    }


@hdk_generator
def task_generate_rtl(model):
    """Task generating RTL.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    rtl = tasks.RtlBuilder(model)

    # because of openocd and lldb
    ia_model = model.get_sibling_model(ia=True).filter_model()
    dbg_task = ia_model.get_task_id('dbg')

    def title(task):
        return 'RTL'

    return {
        'basename': 'rtl',
        'actions': [rtl.run],
        'targets': [],
        'file_dep': rtl.file_dep,
        'task_dep': [dbg_task],
        'uptodate': [codasip.utility.utils.config_changed(rtl.uptodate),
                     codasip.utility.utils.folder_changed(rtl.output_dir,
                                                          includes='*' + codasip.utility.utils.hdl_extension(rtl.lang))
                     ],
        'title': title
    }


@hdk_generator
def task_generate_uvm(model):
    """Task generating UVM Verification tools.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    uvm = tasks.UvmBuilder(model)
    if uvm.skip:
        codasip.utility.logger.warning('Cannot find IA model for generating auto UVM for ', uvm.id)
        return
    hdl_ext = codasip.utility.utils.hdl_extension(uvm.lang)

    ia_model = model.get_sibling_model(ia=True).filter_model()
    dsm_task = ia_model.get_task_id('dsm')

    def title(task):
        return 'UVM Verification (' + ('Auto' if uvm.auto else 'User') + ")"

    return {
        'basename': 'uvm',
        'actions': [uvm.run],
        'targets': [],
        'file_dep': uvm.file_dep,
        'task_dep': [dsm_task],
        'uptodate': [codasip.utility.utils.config_changed(uvm.uptodate),
                     codasip.utility.utils.folder_changed(uvm.output_dir,
                                                          includes=['*' + hdl_ext, '*.f', '*.svh', '*.sv', '*.tcl', '*.py', '*.dll', '*.so']),
                     codasip.utility.utils.folder_changed(uvm.rtl_dir,
                                                          includes=['*' + hdl_ext, '*.f', '*.cfg', '*.json'])
                     ],
        'title': title
    }


@hdk_generator
def task_hdk(model):
    """Group task to generate entire HDK.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    # Asip tasks
    hdk_tasks = ['rtl', 'uvm']

    def title(task):
        return 'HDK'

    return {
        'basename': 'hdk',
        'actions': None,  # This is just group of tasks
        'task_dep': [model.get_task_id(t) for t in hdk_tasks],
        'title': title
    }


@codasip.utility.filter_decorator.filter(type=codasip.build.project.CodalProject)
def task_publish_ip(project):
    """

    :param project: Instance of current project
    :return: DOIT format dictionary of task
    :rtype: dict
    """
    # Load publication configuration
    sdk_include = project.config['publication.sdk']
    hdk_include = project.config['publication.hdk']
    hdk_uvm_include = project.config['publication.hdk-uvm']
    doc_include = project.config['publication.doc']
    tests_include = project.config['publication.tests']
    publish_path = os.path.join(str(project.work_dir), 'publish')

    task_dep = []
    # User-specified models to publish
    model_design_paths = project.config['publication.publish-models']
    # if no models are selected, use all
    if not model_design_paths:
        model_design_paths = [model.id for model in project.list_models()]

    models = {}
    for m in project.list_models():
        models[m.id] = m

    # Find all models set by user
    publish_models = []
    for id in model_design_paths:
        model = models.get(id)
        if not model:
            codasip.utility.logger.warning('Model {} for publication was not found, skipping.', id)
            continue

        # Add subtasks
        publish_models.append(model)
        if sdk_include:
            task_dep.append(model.get_task_id('sdk'))

        # Add subtasks - ca toplevel HDKs
        if hdk_include and model.hdk:
            task_dep.append(model.get_task_id('rtl'))
            if hdk_uvm_include:
                task_dep.append(model.get_task_id('uvm'))

    def publish_doc(publish_path):
        """Copy documentation.

        :param publish_path:
        """
        path = os.path.join(project.dir, 'doc')

        if not os.path.isdir(path):
            return

        codasip.utility.logger.info('Copying {} documentation', project.name)
        for root, dirs, files in os.walk(path):
            # relative directory
            rel_dir = os.path.relpath(root, path)

            for fname in files:
                # skip some files and extensions
                if fname in ['.gitignore'] or codasip.get_extension(fname) in ['.pyo', '.pyc']:
                    continue

                target = os.path.join(publish_path, 'doc', rel_dir)
                if not os.path.isdir(target):
                    codasip.utility.utils.makedirs(target)

                codasip.utility.utils.copy(os.path.join(root, fname), os.path.join(target, fname))

            # skip some directories
            dirs[:] = [d for d in dirs if d != 'private']

    def publish_ip(publish_path, models):
        """

        :param publish_path:
        :param models:
        """
        codasip.utility.logger.info('Cleaning publish output directory')
        # Clean publication directory
        if os.path.isdir(publish_path):
            codasip.rmtree(publish_path, ignore_errors=True, content_only=True)
        else:
            codasip.utility.utils.makedirs(publish_path)

        # Copy tests
        tests_root = os.path.join(project.dir, 'tests')
        if tests_include and os.path.isdir(tests_root):
            codasip.utility.logger.info('Copying tests')
            codasip.copy(tests_root, publish_path, copy_root=True)

        # merge SDK and HDK xml models per directory
        target_sdk = codasip.testsuite.sdk.SdkXml()
        target_hdk = codasip.testsuite.hdk.HdkXml()

        for model in models:
            # Copy SDK. Sdk might be missing (e.g. CA ASIP SDK with disabled ASIP tools build)
            if sdk_include and os.path.isdir(model.sdk_dir):
                codasip.utility.logger.info('Publishing {} SDK', model.id)
                output = os.path.join(publish_path, 'sdk')
                if not os.path.isdir(output):
                    codasip.utility.utils.makedirs(output)

                target_sdk.add_model(model.sdk)
                codasip.copy(model.sdk_dir, output)

            # Copy HDK and create new Hdk handler, hdk is top-level only so no project hierarchy
            if hdk_include and model.hdk:
                codasip.utility.logger.info('Publishing {} HDK', model.id)
                output = os.path.join(publish_path, 'hdk')
                if not os.path.isdir(output):
                    codasip.utility.utils.makedirs(output)

                target_hdk.add_model(model.hdk)
                codasip.copy(model.hdk_dir, output)

        # save merged xml
        if target_sdk.models:
            target_sdk.save(path=os.path.join(publish_path, 'sdk'),
                            custom_id=model.config['sdk-id'])
        if target_hdk.models:
            target_hdk.save(path=os.path.join(publish_path, 'hdk'),
                            custom_id=model.config['hdk-id'])

    def pack(publish_path, output):
        """Pack the package. Use another function so hooks can alter the behavior.

        :param publish_path:
        :param output:

        """
        # just filename
        exclude_filenames = ['report.txt', 'sim_exit_code', 'vsim.wlf', 'modelsim.ini']
        # just directory
        exclude_dirs = ['uvm/questa/work', 'uvm/riviera/work', 'uvm/xexes']
        # any path
        exclude_paths = ['*.ucdb', '/*.zip']

        codasip.utility.logger.info("Creating archive {}", os.path.basename(output))
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(publish_path):
                rel_dir = os.path.relpath(root, publish_path)

                # exclude dirs
                filtered = []
                for d in dirs:
                    rel = os.path.join(rel_dir, d).replace('\\', '/')
                    for e in exclude_dirs:
                        if rel.endswith(e):
                            break
                    else:
                        filtered.append(d)
                dirs[:] = filtered

                for file in files:
                    source = os.path.join(root, file)
                    # do not add itself
                    if source == output:
                        continue

                    # skip some filenames
                    if file in exclude_filenames:
                        continue

                    # exclude path by regular. For file in root use '/<filename>'
                    if root == publish_path:
                        target = '/' + file
                    else:
                        target = os.path.join(rel_dir, file)

                    if any((fnmatch.fnmatch(target, e) for e in exclude_paths)):
                        continue

                    zf.write(source, os.path.join(rel_dir, file))

    # todo: set targets when not archiving
    targets = []
    # first publish sdk and hdk, will clean the output folder
    actions = [(publish_ip, [publish_path, publish_models])]

    # add documentation
    if doc_include:
        actions.append((publish_doc, [publish_path]))

    # create an archive
    if project.config['publication.archive']:
        archive = os.path.join(publish_path, project.package_name + '.zip')
        targets.append(archive)
        actions.append((pack, [publish_path, archive]))

    def title(task):
        return 'IP Publication'

    return {
        'basename': 'publish_ip',
        'actions': actions,
        'task_dep': task_dep,
        'targets': targets,
        'uptodate': [codasip.utility.utils.config_changed(publish_path),
                     codasip.utility.utils.folder_changed(publish_path)],
        'title': title
    }


@codasip.utility.filter_decorator.filter()
def task_testing(model):
    """SDK Testing. Execute Codasip model testsuite.

    :param model: Instance of model.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    tmp_dir = os.path.join(str(model.work_dir), 'tests')

    # get IA SDK model
    if model.ia:
        ia_model = model.filter_model()
    else:
        ia_model = model.get_sibling_model(ia=True).filter_model()

    # get all SDKs
    sdks = [model.sdk_dir] + [ia_model.sdk_dir]
    # get HDK path
    hdks = []
    if not model.ia and model.hdk:
        hdks.append(model.hdk_dir)
    # get design paths for simulator
    model_name = model.name

    paths = []
    path = os.path.join(model.project.dir, 'tests')
    if os.path.isdir(path):
        paths.append(path)

    def run(paths, sdks, hdks, model_id):
        from codasip.testsuite import Testsuite

        suite = Testsuite(test_dir=paths,
                          sdk_dir=sdks,
                          hdk_dir=hdks,
                          work_dir=tmp_dir)
        suite.run(['--model-id=' + model_id])

    task_dep = [model.get_task_id('sdk')]
    if not model.ia:
        task_dep.append(model.get_task_id('hdk'))
        task_dep.append(ia_model.get_task_id('sdk'))

    def title(task):
        return 'Testing'

    return {
        'basename': 'test',
        'actions': [(run, [paths, sdks, hdks, model_name])],
        'task_dep': task_dep,
        'uptodate': [False],
        'title': title
    }


@codasip.utility.filter_decorator.filter(type=codasip.build.project.CodalProject)
def task_remove_options(project):
    """Task generating UVM Verification tools.

    :param project: Instance of current project.
    :return: DOIT format dictionary of task.
    :rtype: dict
    """
    # get codasip version used for preprocessor
    version = codasip.build.configuration.Version(codasip.version)

    # output directory in work dir
    root_dir = os.path.join(str(project.work_dir), 'pruned_project')

    src_dir = str(project.dir)
    dst_dir = os.path.join(root_dir, project.name)

    # get name of IA and CA directory
    model_info = {ia: name and os.path.basename(name) for ia, name in project.model_info.items()}

    # list of file extension intended for options removal
    codasip_ext = [
        '.LDS', '.TD', '.inc',
        '.s', '.S', '.c', '.cpp', '.h',
        '.sem', '.cons',
        '.codal', '.hcodal'
    ]

    options_header = [project.options_header] if project.options_header else []

    def get_preprocessor(ia):
        """Setup preprocessor for IA or CA model.

        :param ia: ``True`` if model is IA type, ``False`` otherwise.
        :return: Set up model preprocessor.
        :rtype: codasip.utility.preprocessor.Preprocessor
        """
        prep = codasip.utility.preprocessor.Preprocessor(line_directive=False)
        prep.includes = options_header
        prep.defines = {
            '__CODALC_VERSION__': version,
            '__CODALC_MAJOR__': version[0],
            '__CODALC_MINOR__': version[1],
            '__CODALC_PATCHLEVEL__': version[2],
            ('__IA_MODEL__' if ia else '__CA_MODEL__'): None
        }
        prep.inc_dirs = [os.path.join(src_dir, 'model', 'share', 'include')]
        if project.asip and model_info[ia]:
            prep.inc_dirs.append(
                os.path.join(src_dir, 'model', model_info[ia], 'include'))

        return prep

    # get preprocessor for IA and CA model
    prep_ia = get_preprocessor(ia=True)
    prep_ca = get_preprocessor(ia=False)

    def is_file_empty(file_path, filters):
        """Check if file is empty.

        It is used by preprocessor to determine if resulting file does not contain any code.
        For shared folders IA and CA have to be used together.

        :param file_path: Path to the tested file.
        :type file_path: str
        :param filters: TODO - comment
        :return: ``True`` if file is empty, ``False`` otherwise.
        :rtype: bool
        """
        for filter in filters:
            with filter.process(file_path) as input:
                if not all(not line.strip() for line in input):
                    return False
        return True

    def copy_file(file_path, target, filters=None, target_file=False):
        """
        Copy file with copy_without_options when it has specific file extension or use basic copy.
        If resulting file is empty it is not copied at all.

        :param file_path: TODO - comment
        :param target:
        :param filters:
        :param target_file:
        """
        if target_file:
            target_dir, file_name = os.path.split(target)
        else:
            target_dir = target
            _, file_name = os.path.split(file_path)
        target_path = os.path.join(target_dir, file_name)
        _, file_ext = os.path.splitext(file_name)
        # default is standard Codasip copy
        copy_fnc = codasip.utility.utils.copy
        if file_ext in codasip_ext:
            # apply filters only on codal files except version.codal
            # version.codal usually contains only preprocessor macros and would be removed
            if not filters or file_ext != '.codal' or file_name == 'version.codal' or (
                    not is_file_empty(file_path, filters)):
                copy_fnc = partial(codasip.utility.utils.copy_without_options, project)
            else:
                codasip.utility.logger.info("Empty file '{}' has been removed", target_path)
                copy_fnc = None
        # copy file only if copy_fnc is set
        if copy_fnc:
            if not os.path.isdir(target_dir):
                codasip.utility.utils.makedirs(target_dir)
            copy_fnc(file_path, target_path)

    def copy_tree(*args, **kwargs):
        """Copy file/directory from src_dir to the same location in dst_dir.

        :param args:
        :param kwargs:
        """
        filters = kwargs.get('filters')
        src_path = os.path.join(src_dir, *args)
        dst_path = os.path.join(dst_dir, *args)

        if not os.path.exists(src_path):
            return

        if 'dst_basename' in kwargs:
            # change destination base name when destination is different
            dst_path = os.path.join(os.path.split(dst_path)[0], kwargs['dst_basename'])
        if os.path.isdir(src_path):
            # copy directory
            for root, _, files in os.walk(src_path, topdown=False):
                target_dir = os.path.join(dst_path, os.path.relpath(root, src_path))
                for file in files:
                    copy_file(os.path.join(root, file), target_dir, filters)
        else:
            copy_file(src_path, dst_path, filters, target_file=True)

    def run():
        """Execute remove options task.

        :return: DOIT format dictionary of task.
        :rtype: dict
        """
        # clear root directory
        if os.path.isdir(root_dir):
            codasip.rmtree(root_dir, ignore_errors=True, content_only=True)
        # create output directory
        codasip.utility.utils.makedirs(dst_dir)

        # copy model
        # shared directory is for both IA and CA
        copy_tree('model', 'share', filters=[prep_ia, prep_ca])

        if model_info[True]:
            # copy IA model if any
            copy_tree('model', model_info[True], dst_basename='ia', filters=[prep_ia])
        if model_info[False]:
            # copy CA model if any
            copy_tree('model', model_info[False], dst_basename='ca', filters=[prep_ca])

        # copy remaining directories and project files
        sources = [
            'hdk', 'doc', 'libs', 'linker', 'presets', 'utils',
            '.cproject', '.project'
        ]
        for source in sources:
            copy_tree(source)

        # copy project file and remove 'ia-model' and 'ca-model'
        config = copy.copy(project.config)
        # rename 'ia' and 'ca' models to generic ones
        if model_info[True]:
            config['general.ia-model'] = 'ia'
        if model_info[False]:
            config['general.ca-model'] = 'ca'
        # remove 'configuration' and 'options' from extern
        externs = config.dict.get('extern') or ()
        for extern in externs:
            extern.pop('configuration', None)
            extern.pop('options', None)

        config.save(os.path.join(dst_dir, 'codal.conf'))

    def title(task):
        return 'Remove Options'

    return {
        'basename': '_remove_options',
        'actions': [run],
        'file_dep': options_header,
        'uptodate': [False],
        'title': title
    }
