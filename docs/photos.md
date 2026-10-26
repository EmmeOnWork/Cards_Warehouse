# Photos

The photos of the items live in the private bucket `emmeonwork-cards-warehouse-photos` ([the foundations](../infra/foundations/README.md)). They go through the app on the way in, and never on the way out:

- **Upload.** From the item's page, *Scatta o scegli le foto*: the phone offers the camera and the gallery, several photos at once. Up to **20 MB per photo**, as the page says. A photo of a recent phone weighs 3 to 8 MB; Safari on the iPhone sends its HEIC photos as JPEG. Of photos picked together, all go in or none: one over the limit, or a file that is not a photo, refuses the whole batch with its reason. While it is being sent to S3, an upload waits in `/tmp`, a volume of the pod sized for 25 photos at the limit ([the chart](../chart/templates/deployment.yaml)): the rest of the container cannot be written.
- **Showing.** The page shows each photo through a link the app signs with its key, valid for **5 minutes**. The browser downloads the photo straight from S3. The plain address of a photo, without the signature, answers `AccessDenied`, and a link past its 5 minutes answers `Request has expired`. Both are checked by [the foundations' acceptance test](../infra/foundations/tests/acceptance.sh).
- **Order.** The first photo is the cover, the one the channels show first. The arrows move a photo one place.
- **Keys.** Every photo gets a key of its own, `items/<item>/<random>.<extension>`, which the database keeps: the app never overwrites a photo in the bucket.
- **Deleting.** *Elimina* removes the photo from the item and from the bucket. The bucket keeps versions: S3 puts a *delete marker* over the photo and keeps the photo itself as a previous version. The app's key can delete objects but not their versions, so neither the app nor a stolen key can destroy a photo. Previous versions stay until someone removes them by hand. They cost what the photo cost, cents per GB a month.

Velero does not back up the photos ([gitops](../gitops/README.md)): they are already in S3, protected by those versions.

## Recovering a photo deleted from the app

The item no longer has the photo: you recover it from its previous version, then upload it again. Inside `make shell`, after `aws login --remote`:

1. Note the item's number, the one in the address of its page: `/items/<number>`.
2. List what the bucket holds for that item, photos and delete markers, with their dates:

   ```sh
   aws s3api list-object-versions --bucket emmeonwork-cards-warehouse-photos --prefix items/<number>/ \
     --query '{photos: Versions[].[LastModified, Key, VersionId], deleted: DeleteMarkers[].[LastModified, Key]}' \
     --output table
   ```

   A deleted photo is a key that appears in both lists. In `photos` its `VersionId` is the photo before the delete.
3. Download that version into `recovered-photos/`, a folder of the repository that Git ignores:

   ```sh
   mkdir -p recovered-photos
   aws s3api get-object --bucket emmeonwork-cards-warehouse-photos --key <key> --version-id <VersionId> \
     recovered-photos/<key's last part>
   ```

4. On the PC, open the item's page, `http://127.0.0.1:8000/items/<number>`, and upload the file from `recovered-photos/`. The photo goes last: move it where it was with the arrows.
5. Delete the file from `recovered-photos/`.

## A photo broken on the item's page

The item still has the photo, but its link answers `NoSuchKey`. The photo was deleted from the bucket while the database kept it: by hand from the console, or by the app after the backup the database was restored from. Removing its delete marker makes it visible again, at the same key, and nothing changes in the app:

1. Open the broken photo in a new tab: its address, up to the `?`, ends with its key, `items/<number>/<name>`.
2. Find the delete marker of that key, and remove it. Only removing it needs the full access of `aws login`: the app's key cannot do it.

   ```sh
   aws s3api list-object-versions --bucket emmeonwork-cards-warehouse-photos --prefix <key> \
     --query 'DeleteMarkers[?IsLatest].VersionId' --output text
   aws s3api delete-object --bucket emmeonwork-cards-warehouse-photos --key <key> --version-id <that VersionId>
   ```

3. Reload the item's page.
