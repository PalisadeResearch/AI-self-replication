{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/release-25.11";
  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system: with nixpkgs.legacyPackages.${system}; {
        devShells.default = mkShellNoCC {
          packages = [
            ninja
            svgo
            typst
            uv
          ];
        };
      }
    );
}
