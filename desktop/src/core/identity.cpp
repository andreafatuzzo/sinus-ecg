#include "core/identity.hpp"

#include <string>
#include <string_view>

#include "sinus/dsp/version.hpp"

namespace sinus::desktop::core {

namespace {

void append_item(std::string& text, std::string_view name, const ItemIdentity& item) {
  text.append(name).append(" ").append(item.version);
  text.append(", source SHA-256 ").append(item.source_sha256).append("\n");
}

}  // namespace

std::string identity_text(const IdentityInputs& inputs) {
  std::string text;
  append_item(text, "sinus-desktop", inputs.desktop);
  append_item(text, "sinus-dsp", inputs.library);
  text.append("Qt ").append(inputs.build.qt_build_version).append(" at build, ");
  text.append(inputs.qt_runtime_version).append(" at run time\n");
  text.append("Compiler ").append(inputs.build.compiler);
  text.append(", build type ").append(inputs.build.build_type).append("\n");
  text.append(inputs.build.other_qt_allowed
                  ? "Qt version check: off (SINUS_DESKTOP_ALLOW_OTHER_QT)\n"
                  : "Qt version check: on\n");
  return text;
}

std::string current_identity_text(std::string_view qt_runtime_version) {
  const sinus::dsp::LibraryIdentity library = sinus::dsp::library_identity();
  return identity_text(IdentityInputs{desktop_identity(),
                                      ItemIdentity{library.version, library.source_sha256},
                                      build_info(), qt_runtime_version});
}

}  // namespace sinus::desktop::core
