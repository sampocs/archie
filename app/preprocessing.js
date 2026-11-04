// Runs inside the Safari page when shared, so it sees the article exactly as the logged-in user does
class ShareExtensionPreprocessor {
  run(args) {
    const root = document.querySelector("article") ?? document.body;
    args.completionFunction({
      url: window.location.href,
      title: document.title,
      text: root.innerText,
    });
  }
}

var ExtensionPreprocessingJS = new ShareExtensionPreprocessor();
