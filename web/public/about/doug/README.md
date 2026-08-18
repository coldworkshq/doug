# Doug photos

The `/about` page's gallery (`web/app/about/page.tsx`, `PHOTOS`) reads these
four filenames directly from this folder. Drop the real files in with these
exact names and the gallery picks them up — no code change needed.

| filename             | what it is                                    |
| --------------------- | ---------------------------------------------- |
| `kitchen-selfie.jpg`  | Andrew and Doug, nose to nose in the kitchen   |
| `couch-loaf.jpg`      | Doug loafed over the back of the couch         |
| `rock-hike.jpg`       | Doug and Andrew sitting on rocks after a hike  |
| `nose-boop.jpg`       | Extreme close-up of Doug's nose                |

Until all four exist, the gallery renders broken-image icons in their place
— nothing hides that they're missing.

This file itself isn't referenced anywhere; it only exists so git tracks an
otherwise-empty directory. Delete it once the real photos land.
