// Developer's unit tests of the reference records (architecture-m3.md 17.7): the pinned lists and
// check_reference_record on the fixtures refdb and refdb_bad and on lists written by the tests.

#include <gtest/gtest.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>
#include <system_error>

#include "core/mains.hpp"
#include "core/reference_databases.hpp"
#include "core/sha256.hpp"
#include "core/wfdb_status.hpp"
#include "temp_folder.hpp"

namespace {

using sinus::desktop::core::check_reference_record;
using sinus::desktop::core::kReferenceDatabases;
using sinus::desktop::core::MainsFrequency;
using sinus::desktop::core::ReferenceCheck;
using sinus::desktop::core::ReferenceDatabase;
using sinus::desktop::core::Sha256;
using sinus::desktop::core::to_hex;
using sinus::desktop::core::WfdbResult;
using sinus::desktop::core::WfdbStatus;
using sinus::desktop::test::TempFolder;

const std::filesystem::path kFixtures =
    std::filesystem::path(SINUS_DESKTOP_TEST_REPO_ROOT) / "desktop" / "tests" / "fixtures" / "wfdb";

std::string file_bytes(const std::filesystem::path& path) {
  std::ifstream file(path, std::ios::binary);
  return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}

std::string sha256_hex(const std::string& text) {
  Sha256 hash;
  // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast): the bytes of the text.
  hash.update(reinterpret_cast<const std::uint8_t*>(text.data()), text.size());
  return to_hex(hash.finish());
}

// A database whose pinned list is `list_text`; `digest` keeps the text alive.
struct Injected {
  std::string digest;
  std::array<ReferenceDatabase, 2> databases;
};

Injected injected(const std::string& list_text) {
  Injected out;
  out.digest = sha256_hex(list_text);
  return out;
}

struct Checked {
  WfdbResult result;
  ReferenceCheck check = ReferenceCheck::kVerified;
  const ReferenceDatabase* database = nullptr;
};

// Checks `record_path` against kReferenceDatabases and a test database for `list_text`.
Checked check(const std::filesystem::path& record_path, const std::string& list_text) {
  Injected data = injected(list_text);
  data.databases.at(0) = kReferenceDatabases.at(0);
  data.databases.at(1) = {"test", "1", "Test Database", data.digest, MainsFrequency::k60Hz};
  Checked out;
  out.result = check_reference_record(record_path, data.databases.data(), data.databases.size(),
                                      out.check, out.database);
  if (out.database != nullptr) {
    EXPECT_EQ(out.database, &data.databases.at(1));
    out.database = nullptr;  // the array ends here
  }
  return out;
}

TEST(ReferenceDatabases, AreMitdbAndNstdbWithTheirPinnedLists) {
  ASSERT_EQ(kReferenceDatabases.size(), 2U);
  EXPECT_EQ(kReferenceDatabases.at(0).slug, "mitdb");
  EXPECT_EQ(kReferenceDatabases.at(0).version, "1.0.0");
  EXPECT_EQ(kReferenceDatabases.at(0).title, "MIT-BIH Arrhythmia Database");
  EXPECT_EQ(kReferenceDatabases.at(1).slug, "nstdb");
  EXPECT_EQ(kReferenceDatabases.at(1).title, "MIT-BIH Noise Stress Test Database");
  for (const ReferenceDatabase& database : kReferenceDatabases) {
    EXPECT_EQ(database.checksum_list_sha256.size(), 64U);
    EXPECT_EQ(database.mains, MainsFrequency::k60Hz);
  }
}

TEST(CheckReferenceRecord, VerifiesTheFixtureFolder) {
  const std::string list = file_bytes(kFixtures / "refdb" / "SHA256SUMS.txt");
  Injected data = injected(list);
  data.databases.at(0) = kReferenceDatabases.at(1);
  data.databases.at(1) = {"test", "1", "Test Database", data.digest, MainsFrequency::k60Hz};
  ReferenceCheck result_check = ReferenceCheck::kNotReference;
  const ReferenceDatabase* database = nullptr;
  const WfdbResult result =
      check_reference_record(kFixtures / "refdb" / "ref1", data.databases.data(),
                             data.databases.size(), result_check, database);
  EXPECT_TRUE(result.ok()) << result.message;
  EXPECT_EQ(result_check, ReferenceCheck::kVerified);
  EXPECT_EQ(database, &data.databases.at(1));
}

TEST(CheckReferenceRecord, RejectsTheDamagedFixtureFolder) {
  const std::string list = file_bytes(kFixtures / "refdb" / "SHA256SUMS.txt");
  const Checked checked = check(kFixtures / "refdb_bad" / "ref1", list);
  EXPECT_EQ(checked.result.status, WfdbStatus::kReferenceMismatch);
  EXPECT_EQ(checked.result.message,
            "ref1: ref1.dat does not match the verified checksum list of the Test Database");
}

TEST(CheckReferenceRecord, OtherFoldersAreNotReference) {
  // No list next to the record.
  Checked checked = check(kFixtures / "f16_one", "");
  EXPECT_TRUE(checked.result.ok());
  EXPECT_EQ(checked.check, ReferenceCheck::kNotReference);
  // A list that is none of the databases'.
  checked = check(kFixtures / "refdb" / "ref1", "another list");
  EXPECT_TRUE(checked.result.ok());
  EXPECT_EQ(checked.check, ReferenceCheck::kNotReference);
  // A record that the verified list does not name.
  const std::string list = file_bytes(kFixtures / "refdb" / "SHA256SUMS.txt");
  for (const char* name : {"ref", "ref1x", "ref1.dat"}) {
    checked = check(kFixtures / "refdb" / name, list);
    EXPECT_TRUE(checked.result.ok()) << name;
    EXPECT_EQ(checked.check, ReferenceCheck::kNotReference) << name;
  }
}

class CheckReferenceList : public ::testing::Test {
 protected:
  // Writes the files of record r and the list `text`, and checks r.
  Checked check_list(const std::string& text) {
    folder_.write("r.hea", "header");
    folder_.write("r.dat", "data");
    folder_.write("SHA256SUMS.txt", text);
    return check(folder_.path() / "r", text);
  }
  static std::string entry(const std::string& content, const std::string& separator,
                           const std::string& path) {
    return sha256_hex(content) + separator + path + "\n";
  }

  TempFolder folder_;
};

TEST_F(CheckReferenceList, AcceptsTheFormsOfSha256sum) {
  std::string upper = sha256_hex("data");
  for (char& c : upper) {
    c = (c >= 'a' && c <= 'f') ? static_cast<char>(c - 'a' + 'A') : c;
  }
  const std::string text = entry("header", " ", "r.hea") + upper + " *r.dat\r\n\n" +
                           entry("other", "  ", "x/r.dat") + entry("other", "  ", "r") +
                           entry("other", "  ", "s.dat");
  const Checked checked = check_list(text);
  EXPECT_TRUE(checked.result.ok()) << checked.result.message;
  EXPECT_EQ(checked.check, ReferenceCheck::kVerified);
}

TEST_F(CheckReferenceList, NamesTheFirstFileThatDiffersOrIsMissing) {
  Checked checked = check_list(entry("header", "  ", "r.hea") + entry("other", "  ", "r.dat"));
  EXPECT_EQ(checked.result.status, WfdbStatus::kReferenceMismatch);
  EXPECT_NE(checked.result.message.find("r.dat does not match"), std::string::npos);
  checked = check_list(entry("x", "  ", "r.atr") + entry("other", "  ", "r.dat"));
  EXPECT_EQ(checked.result.status, WfdbStatus::kReferenceMismatch);
  EXPECT_EQ(checked.result.message,
            "r: r.atr is missing from the folder of the verified checksum list of the Test "
            "Database");
}

TEST_F(CheckReferenceList, RejectsAListThatBreaksTheRules) {
  const std::string good = entry("header", "  ", "r.hea");
  for (const std::string& text :
       {std::string(), std::string("\n\r\n"), good + "not an entry\n",
        good + sha256_hex("x").substr(1) + "  r.x\n", good + sha256_hex("x") + "r.x\n",
        good + sha256_hex("x") + "   r.x\n", good + sha256_hex("x") + "  ../r.x\n",
        good + sha256_hex("x") + "  /r.x\n", good + sha256_hex("x") + "  a//r.x\n",
        good + sha256_hex("x") + "  ./r.x\n", good + sha256_hex("x") + "  r.x~\n",
        good + sha256_hex("x") + "  r x\n", good + sha256_hex("x") + "  r.x \n",
        good + sha256_hex("x") + " *\n", good + good}) {
    const Checked checked = check_list(text);
    EXPECT_EQ(checked.result.status, WfdbStatus::kReferenceMismatch) << text;
    EXPECT_EQ(checked.result.message.rfind(
                  "r: SHA256SUMS.txt does not match the verified checksum list of the Test "
                  "Database: ",
                  0),
              0U)
        << checked.result.message;
    EXPECT_EQ(checked.check, ReferenceCheck::kNotReference);
  }
}

TEST_F(CheckReferenceList, AListThatIsNotAFileCannotBeRead) {
  std::error_code error;
  std::filesystem::create_directory(folder_.path() / "SHA256SUMS.txt", error);
  ASSERT_FALSE(error);
  ReferenceCheck result_check = ReferenceCheck::kVerified;
  const ReferenceDatabase* database = &kReferenceDatabases.at(0);
  const WfdbResult result =
      check_reference_record(folder_.path() / "r", kReferenceDatabases.data(),
                             kReferenceDatabases.size(), result_check, database);
  EXPECT_EQ(result.status, WfdbStatus::kCannotRead);
  EXPECT_EQ(result_check, ReferenceCheck::kNotReference);
  EXPECT_EQ(database, nullptr);
}

}  // namespace
