import ExpoModulesCore
import Security
import WidgetKit

/// Stores the widget snapshot in a Keychain item shared with the widget extension, then reloads its timelines.
public class ArchieWidgetModule: Module {
  private let service = "com.sampocs.archie.widget"
  private let account = "today"
  private let accessGroup = "3W3H65F89G.com.sampocs.archie.shared"

  public func definition() -> ModuleDefinition {
    Name("ArchieWidget")

    AsyncFunction("setSnapshot") { (json: String) in
      self.write(data: Data(json.utf8))
      WidgetCenter.shared.reloadAllTimelines()
    }

    AsyncFunction("clear") { () in
      let status = SecItemDelete(self.baseQuery() as CFDictionary)
      if status != errSecSuccess && status != errSecItemNotFound {
        NSLog("ArchieWidget: keychain delete failed (%d)", Int(status))
      }
      WidgetCenter.shared.reloadAllTimelines()
    }
  }

  private func baseQuery() -> [String: Any] {
    return [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrAccount as String: account,
      kSecAttrAccessGroup as String: accessGroup,
    ]
  }

  // Failures are logged and swallowed: the widget is a convenience and must never break the app.
  private func write(data: Data) {
    let update = [kSecValueData as String: data]
    let updateStatus = SecItemUpdate(baseQuery() as CFDictionary, update as CFDictionary)
    if updateStatus == errSecSuccess { return }
    if updateStatus != errSecItemNotFound {
      NSLog("ArchieWidget: keychain update failed (%d)", Int(updateStatus))
      return
    }

    var add = baseQuery()
    add[kSecValueData as String] = data
    add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
    let addStatus = SecItemAdd(add as CFDictionary, nil)
    if addStatus != errSecSuccess {
      NSLog("ArchieWidget: keychain add failed (%d)", Int(addStatus))
    }
  }
}
