#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char executable[PATH_MAX + 1];
    char bootstrap[PATH_MAX + 1];
    ssize_t length = readlink("/proc/self/exe", executable, PATH_MAX);
    if (length < 0) {
        perror("No se pudo localizar el lanzador");
        return 1;
    }
    executable[length] = '\0';

    char *separator = strrchr(executable, '/');
    if (separator == NULL) {
        fprintf(stderr, "La ruta del lanzador no es válida.\n");
        return 1;
    }
    *separator = '\0';

    int written = snprintf(bootstrap, sizeof(bootstrap), "%s/../bootstrap.py", executable);
    if (written < 0 || (size_t)written >= sizeof(bootstrap)) {
        fprintf(stderr, "La ruta de bootstrap.py es demasiado larga.\n");
        return 1;
    }

    char **arguments = calloc((size_t)argc + 2, sizeof(*arguments));
    if (arguments == NULL) {
        perror("No se pudieron preparar los argumentos");
        return 1;
    }
    arguments[0] = "python3";
    arguments[1] = bootstrap;
    for (int i = 1; i < argc; ++i) {
        arguments[i + 1] = argv[i];
    }

    execvp(arguments[0], arguments);
    fprintf(stderr, "No se pudo iniciar Python: %s\n", strerror(errno));
    free(arguments);
    return 1;
}
