#include <gtest/gtest.h>

#include <string>
#include <vector>

#include "core/command_line.hpp"

using sinus::desktop::core::Command;
using sinus::desktop::core::command_from_arguments;

TEST(CommandLine, NoArgumentRuns) {
  EXPECT_EQ(command_from_arguments({"sinus-desktop"}), Command::kRun);
  EXPECT_EQ(command_from_arguments({}), Command::kRun);
}

TEST(CommandLine, VersionPrintsTheIdentity) {
  EXPECT_EQ(command_from_arguments({"sinus-desktop", "--version"}), Command::kPrintVersion);
  EXPECT_EQ(command_from_arguments({"sinus-desktop", "-platform", "offscreen", "--version"}),
            Command::kPrintVersion);
}

TEST(CommandLine, OtherArgumentsAreLeftToQt) {
  EXPECT_EQ(command_from_arguments({"sinus-desktop", "-platform", "offscreen"}), Command::kRun);
  EXPECT_EQ(command_from_arguments({"sinus-desktop", "--versions", "-version"}), Command::kRun);
}

TEST(CommandLine, TheProgramNameIsNotAnArgument) {
  EXPECT_EQ(command_from_arguments({"--version"}), Command::kRun);
}
