class ParakeetDictation < Formula
  include Language::Python::Virtualenv

  desc "A dictation tool powered by Parakeet"
  homepage "https://github.com/osadalakmal/parakeet-dictation"
  url "https://github.com/osadalakmal/parakeet-dictation/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "b90fff2616144305d2540d21d3b41226d93d6f1f05143307c39c028087e83f74"
  license "MIT"
  revision 2

  depends_on "python@3.12"
  depends_on "portaudio" # needed by pyaudio

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      macOS: grant Accessibility and Input Monitoring to your terminal
      (System Settings → Privacy & Security) so global hotkeys work.

      Ensure your pyproject has:
        [project.scripts]
        parakeet-dictation = "parakeet_dictation.main:main"
    EOS
  end

  test do
    system "#{bin}/parakeet-dictation", "--help"
  end
end
