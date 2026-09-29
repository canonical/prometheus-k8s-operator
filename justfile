set allow-duplicate-recipes
set allow-duplicate-variables
import? 'charms.just'

[private]
@default:
  just --list
  echo ""
  echo "For help with a specific recipe, run: just --usage <recipe>"
