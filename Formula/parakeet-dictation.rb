class ParakeetDictation < Formula
  include Language::Python::Virtualenv

  desc "A dictation tool powered by Parakeet"
  homepage "https://github.com/osadalakmal/parakeet-dictation"
  url "https://github.com/osadalakmal/parakeet-dictation/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "0520c70b18d70ae900c9f2503a04861223fe67a5ef79ae93df398086b940465e"
  license "MIT"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/parakeet-dictation", "--help"
  end
end

