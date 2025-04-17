#include "subdir/test_file2.h"
#include "test_file1.h"

int main_global;

void test_top() {}

int main() {
  int main_local = test2_global;

#ifdef macro1

#endif

  test_top();
  test_fun1();
  test_fun2();

  return 0;
}
