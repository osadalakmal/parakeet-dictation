class ParakeetDictation < Formula
  include Language::Python::Virtualenv

  desc "A dictation tool powered by Parakeet"
  homepage "https://github.com/osadalakmal/parakeet-dictation"
  url "https://github.com/osadalakmal/parakeet-dictation/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "39988aa841dded5f26905480f261f19210d551a5b729a37704281c0f11d0aece"
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
