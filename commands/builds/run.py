import sublime
import sublime_plugin
import os
import re
import shlex
from ...core import (
    BuildSystem,
    DependencyManager,
    GenericShell,
    JavaUtils,
    JDKManager,
    Macro,
    MultiThreadProgress,
    Settings,
    StateProperty
)


class JavatarRunCommand(sublime_plugin.WindowCommand):
    progress = None
    total_console = 0

    def build_project(self):
        if not StateProperty().is_project():
            sublime.error_message("Unknown package location")
            return
        for view in self.window.views():
            if JavaUtils().is_java(view) and view.is_dirty():
                if Settings().get("automatic_save"):
                    self.window.run_command("save_all")
                    break
                else:
                    sublime.error_message("Some Java files are not saved")
                    return
        BuildSystem().finish_callback = self.on_build_finish
        error_message = BuildSystem().build_dirs(
            StateProperty().get_source_folders(),
            window=self.window
        )
        if error_message:
            sublime.error_message(error_message)

    def on_build_finish(self, failed):
        if not failed:
            self.run(skip_build=True)

    def get_runnable_files(self, dir_path=None):
        """
        Returns a list of runnable file paths in specified directory and its
            sub-directory

        @param dir_path: a directory path
        """
        if not dir_path:
            return []
        files = []
        for name in os.listdir(dir_path):
            path_name = os.path.join(dir_path, name)
            if (os.path.isdir(path_name) and
                    name not in Settings().get_sublime(
                        "folder_exclude_patterns", []
                    )):
                files += self.get_runnable_files(path_name)
            elif (os.path.isfile(path_name) and
                    self.is_main_class(path_name)):
                files.append(path_name)
        return files

    def is_main_class(self, file_path):
        if not StateProperty().is_java(file_path):
            return False
        datafile = open(file_path, "r")
        data = datafile.read()
        datafile.close()
        main_signature = re.compile("public\\s+static\\s+void\\s+main\\s*\\(\\s*String\\s*\\[\\s*\\]\\s+\\w+\\s*\\)")
        if main_signature.search(data):
            return True
        return False

    def trim_extension(self, file_path):
        filename, ext = os.path.splitext(os.path.basename(file_path))
        for extension in Settings().get("java_extensions"):
            if ext == extension:
                return file_path[:-len(ext)]
        return file_path

    def run_program(self, file_path):
        class_name = self.trim_extension(os.path.basename(file_path))
        full_class_path = JavaUtils().to_package(
            self.trim_extension(file_path)
        ).as_class_path()

        view = self.window.new_file()
        # self.window.set_view_index(view, target_group, target_index)
        view.set_syntax_file("Packages/Javatar/syntax/JavaStackTrace.tmLanguage")
        view.set_name("Running " + class_name + " ...")
        view.set_scratch(True)
        output_location = Macro().parse(Settings().get("build_output_location"))
        dependencies = [output_location] + [
            dependency[0]
            for dependency
            in DependencyManager().get_dependencies()
        ]
        executable = JDKManager().get_executable("run")
        if not executable:
            return
        arguments = Macro().parse(Settings().get("program_arguments"))
        classpath = os.pathsep.join(dependencies)
        run_script = "%s -classpath %s %s" % (
            shlex.quote(executable),
            shlex.quote(classpath),
            full_class_path
        )

        if arguments:
            run_script += " %s" % (arguments)

        console = GenericShell(
            run_script,
            view,
            on_complete=lambda elapse_time, ret, params: self.on_console_close(
                view, class_name, elapse_time, ret, params
            )
        )
        console.set_cwd(Macro().parse(Settings().get("run_location")))
        console.start()

        if not self.progress:
            self.progress = MultiThreadProgress(
                "Preparing console",
                on_all_complete=self.on_all_console_close,
                target="console"
            )

        self.progress.add(console, "")

        self.total_console += 1
        self.progress.set_message("%s console%s running" % (
            self.total_console,
            "s" if self.total_console > 1 else ""
        ))
        if not self.progress.running:
            self.progress.run()

    def on_console_close(self, view, class_name, elapse_time, ret, params):
        self.total_console -= 1
        if self.progress:
            self.progress.set_message("%s console%s running" % (
                self.total_console,
                "s" if self.total_console > 1 else ""
            ))

        if ret is not None:
            view.set_name("%s Ended (Return: %s) [%.2fs]" % (
                class_name, ret, elapse_time
            ))

    def on_all_console_close(self):
        self.progress = None

    def on_select_file(self, index):
        if index < 0:
            return

        self.run_program(self.runnable_files[index])

    def run(self, skip_build=False):
        if not skip_build and Settings().get("automatic_build"):
            self.build_project()
            return

        self.prefix = os.path.dirname(
            os.path.commonprefix(StateProperty().get_project_dirs())
        )

        # Check the current file
        if (not Settings().get("always_ask_to_run") and
            StateProperty().is_project() and
                StateProperty().is_file()):
            if self.is_main_class(self.window.active_view().file_name()):
                self.run_program(self.window.active_view().file_name())
                return

        self.runnable_files = []
        # Check the whole project
        for source_folder in StateProperty().get_source_folders():
            self.runnable_files += self.get_runnable_files(source_folder)
        if len(self.runnable_files) > 1:
            self.window.show_quick_panel(
                [
                    [
                        os.path.basename(file_path),
                        os.path.relpath(file_path, self.prefix)
                    ]
                    for file_path
                    in self.runnable_files
                ], self.on_select_file
            )
        elif len(self.runnable_files) == 1:
            self.run_program(self.runnable_files[0])
        else:
            sublime.error_message("No main class found in the project")
