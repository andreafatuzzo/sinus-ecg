# Qt version check (architecture-m3.md 15.3, 15.14): the Qt found must be the version of
# qt/version.txt, unless SINUS_DESKTOP_ALLOW_OTHER_QT is ON (local exploration only; the identity
# of the build states it; CI never sets it).
file(STRINGS "${PROJECT_SOURCE_DIR}/qt/version.txt" SINUS_DESKTOP_QT_PIN LIMIT_COUNT 1)
string(STRIP "${SINUS_DESKTOP_QT_PIN}" SINUS_DESKTOP_QT_PIN)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
             "${PROJECT_SOURCE_DIR}/qt/version.txt")
if(NOT Qt6_VERSION STREQUAL SINUS_DESKTOP_QT_PIN)
  if(SINUS_DESKTOP_ALLOW_OTHER_QT)
    message(WARNING "Qt ${Qt6_VERSION} is not the pinned Qt ${SINUS_DESKTOP_QT_PIN} "
                    "(accepted by SINUS_DESKTOP_ALLOW_OTHER_QT; stated in the identity)")
  else()
    message(FATAL_ERROR "Qt ${Qt6_VERSION} found (${Qt6_DIR}), but desktop/qt/version.txt pins "
                        "Qt ${SINUS_DESKTOP_QT_PIN}. Install it with desktop/qt/install_qt.py.")
  endif()
endif()
