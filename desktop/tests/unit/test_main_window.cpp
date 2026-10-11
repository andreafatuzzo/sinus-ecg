#include <gtest/gtest.h>

#include <QGuiApplication>
#include <QString>
#include <QTest>

#include "ui/main_window.hpp"

TEST(MainWindow, RunsOnTheOffscreenPlatform) {
  EXPECT_EQ(QGuiApplication::platformName(), QStringLiteral("offscreen"));
}

TEST(MainWindow, ShowsWithItsTitle) {
  sinus::desktop::ui::MainWindow window;
  window.show();
  EXPECT_TRUE(QTest::qWaitForWindowExposed(&window));
  EXPECT_TRUE(window.isVisible());
  EXPECT_EQ(window.windowTitle(), QStringLiteral("Sinus"));
}
