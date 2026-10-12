#include "ui/main_window.hpp"

#include <QMainWindow>
#include <QString>
#include <QWidget>

namespace sinus::desktop::ui {

MainWindow::MainWindow(QWidget* parent) : QMainWindow(parent) {
  setObjectName(QStringLiteral("mainWindow"));
  setWindowTitle(QStringLiteral("Sinus"));
}

}  // namespace sinus::desktop::ui
