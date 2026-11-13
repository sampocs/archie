Pod::Spec.new do |s|
  s.name           = 'ArchieWidget'
  s.version        = '1.0.0'
  s.summary        = 'Writes the lock-screen widget snapshot to the shared Keychain'
  s.description    = 'Local Expo module that stores the Today snapshot in a Keychain item the widget extension reads.'
  s.author         = ''
  s.homepage       = 'https://docs.expo.dev/modules/'
  s.platforms      = { :ios => '16.4' }
  s.source         = { git: '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }

  s.source_files = "**/*.{h,m,mm,swift,hpp,cpp}"
end
