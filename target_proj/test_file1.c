#include "test_file1.h"
#include "subdir/test_file2.h"

int test2_global = 0;

void test_fun1(void) {
  test_fun2();

#ifdef macro2
#endif
}
