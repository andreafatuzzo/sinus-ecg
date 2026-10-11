#pragma once

// Main window of the desktop application (architecture-m3.md 15.13); empty until its content
// lands with the user-interface group.

#include <QMainWindow>

class QWidget;

namespace sinus::desktop::ui {

class MainWindow : public QMainWindow {
  Q_OBJECT

 public:
  explicit MainWindow(QWidget* parent = nullptr);
};

}  // namespace sinus::desktop::ui
