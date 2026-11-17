# Upload this package from your MacBook

This is a portable source-and-documentation package — no remote repository was created by the packaging work

1. Copy `kiwi-litchi-repo-package.zip` to the MacBook and unzip it
2. Open the extracted `kiwi-litchi` folder and review README, screenshots, metrics, provenance and model limits
3. On GitHub, create a public repository named `kiwi-litchi`
4. Upload the contents of this folder through GitHub's Add file / Upload files workflow, or use Git below
5. Keep the `.gitignore` file and the font licence in the upload

For a Git upload, replace YOUR_USERNAME with your actual GitHub account

```bash
cd /path/to/kiwi-litchi
git init -b main
git add .
git commit -m "Add Kiwi and Litchi app, workflow, screenshots and verification"
git remote add origin https://github.com/YOUR_USERNAME/kiwi-litchi.git
git push -u origin main
```

Do not create a second README on GitHub before pushing an existing local commit

The deployment scripts and systemd units target Linux Mint — uploading from a Mac does not make the Wine/Tally setup a macOS installer

Model files and TallyPrime are separately downloaded from their respective vendors and are not included here
