// GoogleTest main of the Qt test executables (architecture-m3.md 15.16): one QApplication on the
// offscreen platform for the whole run, so that widgets work without a window system.

#include <gtest/gtest.h>

#include <QApplication>
#include <QByteArray>
#include <QtGlobal>

int main(int argc, char** argv) {
  qputenv("QT_QPA_PLATFORM", QByteArrayLiteral("offscreen"));
  testing::InitGoogleTest(&argc, argv);
  const QApplication application(argc, argv);
  return RUN_ALL_TESTS();
}
