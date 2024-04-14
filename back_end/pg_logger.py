# Online Python Tutor
# Copyright (C) 2010-2011 Philip J. Guo (philip@pgbovine.net)
# https://github.com/pgbovine/OnlinePythonTutor/
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import bdb  # the KEY import here!
import sys
import io
import inspect
from back_end.pg_encode import encode

# This is the meat of the Online Python Tutor back-end. It implements a
# full logger for Python program execution (based on pdb, the standard
# Python debugger imported via the bdb module), printing out the values
# of all in-scope data structures after each executed instruction.

MAX_EXECUTED_LINES = 200


class PGLogger(bdb.Bdb):
    def __init__(self, max_executed_lines=MAX_EXECUTED_LINES, ignore_id=False):
        bdb.Bdb.__init__(self)

        # each entry contains a dict with the information for a single executed line
        self.trace = []

        # don"t print out a custom ID for each object (for regression testing)
        self.ignore_id = ignore_id

        # upper-bound on the number of executed lines, in order to guard against infinite loops
        self.max_executed_lines = max_executed_lines

        # keep track of visited lines
        self.visited_lines = set()

        self.script_lines = []
        self.function_caller = []
        self.end_shift_holder = []

    # Override Bdb methods
    def user_call(self, frame, argument_list):
        """This method is called when there is the remote possibility
        that we ever need to stop in this function."""
        calling_frame = frame.f_back

        # true positions
        positions = inspect.getframeinfo(calling_frame).positions
        start_line = positions.lineno
        start_offset = positions.col_offset
        end_line = positions.end_lineno
        end_offset = positions.end_col_offset

        # relative positions
        end_point = end_offset - len(self.script_lines[end_line - 1])

        if not self.function_caller or id(calling_frame) != self.function_caller[-1]["calling_frame_id"]:
            full_calling_code = "\n".join(self.script_lines[start_line - 1: end_line])
            calling_code_snippet = full_calling_code[start_offset: end_point] if end_point \
                else full_calling_code[start_offset:]

            self.function_caller.append({
                "calling_frame_id": id(calling_frame), "code": full_calling_code,
                "true_positions": [[start_line, start_offset], [end_line, end_offset]],
                "relative_positions": [start_offset, start_offset + len(calling_code_snippet)]
            })
        else:
            relative_start_position = start_offset
            relative_end_position = end_offset
            for pos, diff in self.end_shift_holder:
                if relative_start_position > pos:
                    relative_start_position -= diff
                if relative_end_position > pos:
                    relative_end_position -= diff

            self.function_caller[-1].update({
                "true_positions": [[start_line, start_offset], [end_line, end_offset]],
                "relative_positions": [relative_start_position, relative_end_position]
            })

    def user_line(self, frame):
        """This function is called when we stop or break at this line."""
        if self.function_caller and id(frame) == self.function_caller[-1]["calling_frame_id"]:
            self.function_caller.pop()
            self.end_shift_holder = []

        self.interaction(frame, "step_line")

    def user_return(self, frame, return_value):
        """This function is called when a return trap is set here."""
        while self.function_caller and id(frame.f_back) != self.function_caller[-1]["calling_frame_id"]:
            self.function_caller.pop()
            self.end_shift_holder = []

        if self.function_caller:
            last_caller = self.function_caller[-1]
            code = last_caller["code"]
            [pos_start, pos_end] = last_caller["relative_positions"]
            ret = str(return_value)

            last_caller["code"] = code.replace(code[pos_start: pos_end], ret, 1)
            last_caller["relative_positions"] = [pos_start, pos_start + len(ret)]

            self.end_shift_holder.append([pos_end, pos_end - pos_start - len(ret)])

        frame.f_locals["__return__"] = return_value
        self.interaction(frame, "return")

    def user_exception(self, frame, exc_info):
        """This function is called if an exception occurs,
        but only if we are to stop at or just below this level."""
        frame.f_locals["__exception__"] = exc_info[:2]
        self.interaction(frame, "exception")

    # General interaction function
    def interaction(self, frame, event_type):
        # each element is a pair of (function name, ENCODED locals dict)
        encoded_stack_locals = []

        # climb up until you find "<module>", which is (hopefully) the global scope
        cur_frame = final_frame = frame
        while True:
            cur_name = cur_frame.f_code.co_name
            if cur_name == "<module>":
                break

            # special case for lambdas - grab their line numbers too
            if cur_name == "<lambda>":
                cur_name = f"lambda on line {cur_frame.f_code.co_firstlineno}"
            elif cur_name == "":
                cur_name = "unnamed function"

            encoded_stack_locals.append((
                cur_name, {k: encode(v, set(), self.ignore_id) for k, v in cur_frame.f_locals.items() if
                           k not in {"__stdout__", "__builtins__", "__name__", "__exception__", "__module__"}}
            ))
            cur_frame = cur_frame.f_back

        trace_entry = {"line": final_frame.f_lineno, "event": event_type, "visited_lines": list(self.visited_lines),
                       "func_name": final_frame.f_code.co_name,
                       "globals": {k: encode(v, set(), self.ignore_id) for k, v in final_frame.f_globals.items() if
                                   k not in {"__stdout__", "__builtins__", "__name__", "__exception__", "__return__"}},
                       "stack_locals": encoded_stack_locals, "stdout": final_frame.f_globals["__stdout__"].getvalue()}

        if self.function_caller:
            trace_entry["caller_info"] = self.function_caller[-1].copy()

        # if there's an exception, then record its info:
        if event_type == "exception":
            # always check in f_locals
            exc = frame.f_locals["__exception__"]
            trace_entry["exception_msg"] = f"{exc[0].__name__}: {exc[1]}"

        # Added after as currently highlighted line has not been executed yet
        self.visited_lines.add(final_frame.f_lineno)
        self.trace.append(trace_entry)

        if len(self.trace) >= self.max_executed_lines:
            self.trace.append({"event": "instruction_limit_reached",
                               "exception_msg": f"(stopped after {self.max_executed_lines} steps to prevent possible "
                                                "infinite loop)"})
            self.set_quit()

    def runscript(self, script_str):
        self.script_lines = script_str.split("\n")

        # redirect stdout of the user program to a memory buffer
        user_stdout = io.StringIO()
        sys.stdout = user_stdout
        user_globals = {"__name__": "__main__",
                        # try to "sandbox" the user script by not allowing certain potentially dangerous operations:
                        "__builtins__": {k: v for k, v in __builtins__.items() if k not in
                                         {"reload", "input", "apply", "open", "compile", "__import__", "file", "eval",
                                          "execfile", "exit", "quit", "raw_input", "dir", "globals", "locals", "vars"}},
                        "__stdout__": user_stdout}

        try:
            self.run(script_str, user_globals, user_globals)
        except Exception as exc:
            import traceback; traceback.print_exc()

            trace_entry = {"event": "uncaught_exception"}

            if hasattr(exc, "lineno"):
                trace_entry["line"] = exc.lineno
            if hasattr(exc, "offset"):
                trace_entry["offset"] = exc.offset

            if hasattr(exc, "msg"):
                trace_entry["exception_msg"] = "Error: " + exc.msg
            else:
                trace_entry["exception_msg"] = "Unknown error"

            self.trace.append(trace_entry)

        # finalise results
        sys.stdout = sys.__stdout__
        assert len(self.trace) <= (self.max_executed_lines + 1)

        # filter all entries after "return" from "<module>", since they
        # seem extraneous:
        res = []
        for e in self.trace:
            res.append(e)
            if e["event"] == "return" and e["func_name"] == "<module>":
                break

        # another hack: if the SECOND to last entry is an "exception"
        # and the last entry is return from <module>, then axe the last
        # entry, for aesthetic reasons :)
        if len(res) >= 2 and res[-2]["event"] == "exception" and \
                res[-1]["event"] == "return" and res[-1]["func_name"] == "<module>":
            res.pop()

        return res
