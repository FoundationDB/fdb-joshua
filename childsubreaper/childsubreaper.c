/*
 * childsubreaper.c
 *
 * This source file is part of the FoundationDB open source project
 *
 * Copyright 2013-2018 Apple Inc. and the FoundationDB project authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
/*
 *
 * This C code wraps a call to prctl(PR_SET_CHILD_SUBREAPER) so that it is available to
 * be called by a Python process. Hopefully, this will make it easier to deal with orphaned
 * grandchildren as they should now be inherited by the Python process that calls
 * "childsubreaper.set_child_subreaper" rather than init.
 */
#include <Python.h>

#ifdef __linux__
#include <sys/prctl.h>
#include <linux/prctl.h>
#endif

// Std C: Function declaration.
static PyObject *childsubreaper_setchildsubreaper(PyObject *self, PyObject *args);

// Python method table.
static PyMethodDef ChildSubreaperMethods[] = {
    {"set_child_subreaper", childsubreaper_setchildsubreaper, METH_VARARGS, "Set this process as its child subreaper."},
    {NULL, NULL, 0, NULL} /* sentinel */
};

static struct PyModuleDef childsubreaper =
{
    PyModuleDef_HEAD_INIT,
    "childsubreaper", /* name of module */
    "",          /* module documentation, may be NULL */
    -1,          /* size of per-interpreter state of the module, or -1 if the module keeps state in global variables. */
    ChildSubreaperMethods
};

PyMODINIT_FUNC PyInit_childsubreaper(void) {
    return PyModule_Create(&childsubreaper);
}

// prctl(PR_SET_CHILD_SUBREAPER) wrapper method callable from Python.
static PyObject *childsubreaper_setchildsubreaper(PyObject *self, PyObject *args) {
#ifdef PR_SET_CHILD_SUBREAPER
    /* Set this process as its child subreaper. */
    int res;
    res = prctl(PR_SET_CHILD_SUBREAPER, 1L, 0L, 0L, 0L);

    /* Return the return code as a Python object. */
    return Py_BuildValue("i", res);
#else
    /* Just return zero on all other platforms. */
    return Py_BuildValue("i", 0);
#endif
}
