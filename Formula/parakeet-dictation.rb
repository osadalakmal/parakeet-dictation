class ParakeetDictation < Formula
  include Language::Python::Virtualenv

  desc "A dictation tool powered by Parakeet"
  homepage "https://github.com/osadalakmal/parakeet-dictation"
  url "https://github.com/osadalakmal/parakeet-dictation/archive/refs/tags/v0.1.3.tar.gz"
  sha256 "51888410c1a833923987603d90aba9ae2525dc02acc8cc3883b95edcd3c6c26b"
  license "MIT"
  revision 3

  depends_on "python@3.12"
  depends_on "portaudio"   # pyaudio needs this
  depends_on "libsndfile"  # soundfile needs this

  def install
    venv = virtualenv_create(libexec, "python3.12")

    # Ensure build can find native headers/libs
    ENV.append "CFLAGS", "-I#{Formula["portaudio"].opt_include}"
    ENV.append "LDFLAGS", "-L#{Formula["portaudio"].opt_lib}"
    ENV.append "CFLAGS", " -I#{Formula["libsndfile"].opt_include}"
    ENV.append "LDFLAGS", " -L#{Formula["libsndfile"].opt_lib}"

    # Install your package WITH its dependencies and link console scripts
    venv.pip_install_and_link buildpath
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
    # import check and CLI help
    system "#{libexec}/bin/python3.12", "-c", "import parakeet_dictation.main as m; print(m.__file__)"
    system "#{bin}/parakeet-dictation", "--help"
  end
end

