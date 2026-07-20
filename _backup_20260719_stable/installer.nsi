Unicode true

!define PRODUCT_NAME "微机全自动水分测定仪"
!define PRODUCT_VERSION "1.0.0"
!define PRODUCT_PUBLISHER "工业测控"

SetCompressor lzma

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "微机全自动水分测定仪_Setup.exe"
InstallDir "$PROGRAMFILES\${PRODUCT_NAME}"
RequestExecutionLevel admin

Section "Install"
  SetOutPath $INSTDIR
  File /r "..\dist\${PRODUCT_NAME}\*"
  File "..\dist\data.db"
  CreateShortCut "$DESKTOP\${PRODUCT_NAME}.lnk" "$INSTDIR\main_app.exe" "" "$INSTDIR\main_app.exe" 0
  CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk" "$INSTDIR\main_app.exe"
  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\Uninstall.lnk" "$INSTDIR\uninst.exe"
  WriteUninstaller "$INSTDIR\uninst.exe"
SectionEnd

Section "Uninstall"
  RMDir /r $INSTDIR
  Delete "$DESKTOP\${PRODUCT_NAME}.lnk"
  RMDir /r "$SMPROGRAMS\${PRODUCT_NAME}"
SectionEnd
