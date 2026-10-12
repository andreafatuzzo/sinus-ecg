// sinus-desktop: wiring and command line (architecture-m3.md 15.2, 15.12).

#include <QApplication>
#include <cstdio>
#include <iterator>
#include <string>
#include <vector>

#include "core/command_line.hpp"
#include "core/identity.hpp"
#include "io/qt_versions.hpp"
#include "ui/main_window.hpp"

int main(int argc, char* argv[]) {
  const std::vector<std::string> arguments(argv, std::next(argv, argc));
  if (sinus::desktop::core::command_from_arguments(arguments) ==
      sinus::desktop::core::Command::kPrintVersion) {
    // No QApplication: the identity is printed without a display.
    const std::string text =
        sinus::desktop::core::current_identity_text(sinus::desktop::io::qt_runtime_version());
    const bool written = std::fputs(text.c_str(), stdout) >= 0 && std::fflush(stdout) == 0;
    return written ? 0 : 1;
  }

  const QApplication application(argc, argv);
  sinus::desktop::ui::MainWindow window;
  window.show();
  return QApplication::exec();
}
