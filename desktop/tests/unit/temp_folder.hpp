#pragma once

// A fresh folder for the files of one test, removed at the end of the test.

#include <gtest/gtest.h>

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <ios>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace sinus::desktop::test {

class TempFolder {
 public:
  TempFolder() {
    const ::testing::TestInfo* info = ::testing::UnitTest::GetInstance()->current_test_info();
    std::string name = "sinus_desktop_unit_";
    if (info != nullptr) {
      name.append(info->test_suite_name()).append("_").append(info->name());
    }
    std::error_code error;
    path_ = std::filesystem::temp_directory_path(error) / name;
    std::filesystem::remove_all(path_, error);
    std::filesystem::create_directories(path_, error);
    EXPECT_FALSE(error) << error.message();
  }
  ~TempFolder() {
    std::error_code error;
    std::filesystem::remove_all(path_, error);
  }
  TempFolder(const TempFolder&) = delete;
  TempFolder& operator=(const TempFolder&) = delete;
  TempFolder(TempFolder&&) = delete;
  TempFolder& operator=(TempFolder&&) = delete;

  [[nodiscard]] const std::filesystem::path& path() const { return path_; }

  // Writes `bytes` to the file `name` of the folder, in binary mode.
  void write(std::string_view name, std::string_view bytes) const {
    std::ofstream file(path_ / name, std::ios::binary);
    file.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    EXPECT_TRUE(file.good()) << name;
  }

  void write(std::string_view name, const std::vector<std::uint8_t>& bytes) const {
    std::string text;
    text.reserve(bytes.size());
    for (const std::uint8_t byte : bytes) {
      text.push_back(static_cast<char>(byte));
    }
    write(name, text);
  }

 private:
  std::filesystem::path path_;
};

}  // namespace sinus::desktop::test
